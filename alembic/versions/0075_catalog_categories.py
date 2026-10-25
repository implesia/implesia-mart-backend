"""catalog categories: a real category tree; products.category_id replaces the enum

Revision ID: 0075
Revises: 0074
Create Date: 2026-10-25

Expand / backfill / contract in one revision (the data set is small):

1. `categories` table: adjacency list (parent_id), unique slug, SEO fields, ordering. A
   CHECK forbids a category being its own parent; a PostgreSQL trigger forbids cycles.
2. Backfill: the `gadgets` and `fashion` roots always exist. The home tiles of migration
   0074 become categories with the SAME ids (so links and admin state survive); a tile that
   pointed at ?category=gadgets|fashion is the matching root.
3. `products.category_id` (FK, RESTRICT) is backfilled from the old enum, then NOT NULL.
   The enum column stays as a nullable, deprecated copy and its CHECK is dropped.

`home_category_tiles` is left untouched and unused (drop it in a later release).

Downgrade is data preserving: tiles are rebuilt from the categories (same ids, parents,
order), and products get their enum back from their root category (a product under a
non-legacy root falls back to 'gadgets', which is the only lossy step, a product can no
longer be in a custom category once the enum is the only storage).
"""

import re
import unicodedata
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY = {"gadgets": "Trending Gadgets", "fashion": "Gorgeous Dresses"}

CYCLE_FUNCTION = """
CREATE OR REPLACE FUNCTION categories_prevent_cycle() RETURNS trigger AS $$
BEGIN
    IF NEW.parent_id IS NULL THEN
        RETURN NEW;
    END IF;
    -- Serialise concurrent re-parenting so two moves cannot each look safe and still
    -- close a loop together.
    PERFORM pg_advisory_xact_lock(7507501);
    IF EXISTS (
        WITH RECURSIVE up(id, parent_id, n) AS (
            SELECT id, parent_id, 1 FROM categories WHERE id = NEW.parent_id
            UNION ALL
            SELECT c.id, c.parent_id, up.n + 1
            FROM categories c JOIN up ON c.id = up.parent_id
            WHERE up.n < 64
        )
        SELECT 1 FROM up WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'category cycle: % cannot sit under its own descendant', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _slug(text: str, taken: set[str]) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:70] or "category"
    candidate, counter = base, 2
    while candidate in taken:
        candidate = f"{base}-{counter}"
        counter += 1
    taken.add(candidate)
    return candidate


def _is_postgres(bind: Connection) -> bool:
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("image_src", sa.String(length=255), server_default="", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("meta_title", sa.String(length=160), server_default="", nullable=False),
        sa.Column("meta_description", sa.String(length=320), server_default="", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name=op.f("ck_categories_not_own_parent")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name=op.f("fk_categories_parent_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("slug", name=op.f("uq_categories_slug")),
    )
    op.create_index(op.f("ix_categories_parent_id"), "categories", ["parent_id"])
    op.create_index("ix_categories_parent_sort", "categories", ["parent_id", "sort_order"])
    if _is_postgres(bind):
        op.execute(CYCLE_FUNCTION)
        op.execute(
            "CREATE TRIGGER categories_no_cycle BEFORE INSERT OR UPDATE OF parent_id "
            "ON categories FOR EACH ROW EXECUTE FUNCTION categories_prevent_cycle()"
        )

    _backfill_categories(bind)

    # products.category_id: expand, backfill, contract
    op.add_column("products", sa.Column("category_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE products SET category_id = categories.id "
        "FROM categories WHERE categories.slug = products.category"
    )
    missing = bind.execute(
        sa.text("SELECT count(*) FROM products WHERE category_id IS NULL")
    ).scalar()
    if missing:
        raise RuntimeError(f"{missing} products have no matching category; aborting")
    op.alter_column("products", "category_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_products_category_id_categories"),
        "products",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_products_category_storefront",
        "products",
        ["category_id", "published", "status", "price"],
    )
    op.drop_constraint("ck_products_category_known", "products", type_="check")
    op.alter_column("products", "category", existing_type=sa.String(length=32), nullable=True)


def _backfill_categories(bind: Connection) -> None:
    tiles = (
        bind.execute(
            sa.text(
                "SELECT id, parent_id, label, href, image_src, is_active, sort_order, created_at "
                "FROM home_category_tiles ORDER BY sort_order, created_at"
            )
        )
        .mappings()
        .all()
    )
    taken: set[str] = set(LEGACY)
    insert = sa.text(
        "INSERT INTO categories (id, parent_id, slug, name, image_src, is_active, sort_order) "
        "VALUES (:id, NULL, :slug, :name, :image, :active, :order)"
    )
    claimed: dict[str, uuid.UUID] = {}
    rows: list[dict[str, object]] = []
    for tile in tiles:
        legacy = next(
            (
                slug
                for slug in LEGACY
                if tile["parent_id"] is None and f"category={slug}" in tile["href"]
            ),
            None,
        )
        if legacy is not None and legacy not in claimed:
            claimed[legacy] = tile["id"]
            slug = legacy
        else:
            slug = _slug(tile["label"], taken)
        rows.append(
            {
                "id": tile["id"],
                "slug": slug,
                "name": tile["label"],
                "image": tile["image_src"] or "",
                "active": tile["is_active"],
                "order": tile["sort_order"],
            }
        )
    top = len([tile for tile in tiles if tile["parent_id"] is None])
    for legacy, name in LEGACY.items():
        if legacy not in claimed:
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "slug": legacy,
                    "name": name,
                    "image": "",
                    "active": True,
                    "order": top,
                }
            )
            top += 1
    for row in rows:
        bind.execute(insert, row)
    for tile in tiles:
        if tile["parent_id"] is not None:
            bind.execute(
                sa.text("UPDATE categories SET parent_id = :parent WHERE id = :id"),
                {"parent": tile["parent_id"], "id": tile["id"]},
            )


def downgrade() -> None:
    bind = op.get_bind()
    # products: restore the enum from the root category of each product
    op.execute(
        """
        WITH RECURSIVE up(start_id, id, parent_id, slug) AS (
            SELECT id, id, parent_id, slug FROM categories
            UNION ALL
            SELECT up.start_id, c.id, c.parent_id, c.slug
            FROM categories c JOIN up ON c.id = up.parent_id
        ), roots AS (
            SELECT start_id, slug FROM up WHERE parent_id IS NULL
        )
        UPDATE products SET category = CASE
            WHEN roots.slug IN ('gadgets', 'fashion') THEN roots.slug ELSE 'gadgets' END
        FROM roots WHERE roots.start_id = products.category_id
        """
    )
    op.execute("UPDATE products SET category = 'gadgets' WHERE category IS NULL")
    op.alter_column("products", "category", existing_type=sa.String(length=32), nullable=False)
    op.create_check_constraint(
        "ck_products_category_known", "products", "category IN ('gadgets', 'fashion')"
    )
    op.drop_index("ix_products_category_storefront", table_name="products")
    op.drop_constraint(op.f("fk_products_category_id_categories"), "products", type_="foreignkey")
    op.drop_column("products", "category_id")

    # home tiles: rebuild from the categories with the same ids / parents / order
    home = bind.execute(sa.text("SELECT id FROM home_categories WHERE slug = 'home'")).scalar()
    if home is None:
        home = uuid.uuid4()
        bind.execute(
            sa.text("INSERT INTO home_categories (id, slug, heading) VALUES (:id, 'home', '')"),
            {"id": home},
        )
    op.execute("DELETE FROM home_category_tiles")
    op.execute(
        sa.text(
            "INSERT INTO home_category_tiles "
            "(id, category_id, parent_id, label, href, image_src, is_active, sort_order) "
            "SELECT id, :home, NULL, name, '/products?category=' || slug, "
            "image_src, is_active, sort_order "
            "FROM categories"
        ).bindparams(home=home)
    )
    op.execute(
        "UPDATE home_category_tiles t SET parent_id = c.parent_id "
        "FROM categories c WHERE c.id = t.id AND c.parent_id IS NOT NULL"
    )

    if _is_postgres(bind):
        op.execute("DROP TRIGGER IF EXISTS categories_no_cycle ON categories")
        op.execute("DROP FUNCTION IF EXISTS categories_prevent_cycle()")
    op.drop_index("ix_categories_parent_sort", table_name="categories")
    op.drop_index(op.f("ix_categories_parent_id"), table_name="categories")
    op.drop_table("categories")
