"""sustainability hero and point of view keep at most one (optional) photo

Revision ID: 0072
Revises: 0071
Create Date: 2026-10-15

The storefront shows one optional image per sustainability section. The hero keeps its
first photo by (sort_order, created_at); the point of view keeps its first *active* photo
in the same order (it had per-photo visibility). Every other photo, including hidden ones,
moves unchanged into ``sustainability_image_archive``. A unique index on the owner column
then enforces at most one photo. Sections with no photo stay valid. Quality and durability
already stored a single photo in columns and are not touched. Downgrade restores archived
rows with their ids, order and visibility. Media files are not touched.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ARCHIVE = "sustainability_image_archive"
# (image table, owner column, owner table, has is_active)
TABLES: tuple[tuple[str, str, str, bool], ...] = (
    ("sustainability_hero_images", "hero_id", "sustainability_heroes", False),
    ("sustainability_origin_images", "origin_id", "sustainability_origins", True),
)


def upgrade() -> None:
    op.create_table(
        ARCHIVE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_table", sa.String(length=40), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("src", sa.String(length=255), nullable=False),
        sa.Column("alt", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ARCHIVE}")),
    )
    op.create_index(op.f(f"ix_{ARCHIVE}_source_table"), ARCHIVE, ["source_table"])
    for table, owner, _owner_table, has_active in TABLES:
        active = "is_active" if has_active else "true"
        # Active photos rank first, so the kept row is the first active one by order.
        keep = f"""
            SELECT id FROM (
                SELECT id, {active} AS active, ROW_NUMBER() OVER (
                    PARTITION BY {owner}
                    ORDER BY {active} DESC, sort_order, created_at, id
                ) AS rn
                FROM {table}
            ) ranked WHERE rn = 1 AND active
        """
        op.execute(
            f"""
            INSERT INTO {ARCHIVE}
                (id, source_table, owner_id, src, alt, is_active, sort_order, created_at)
            SELECT t.id, '{table}', t.{owner}, t.src, t.alt, {"t." if has_active else ""}{active},
                   t.sort_order, t.created_at
            FROM {table} t
            WHERE t.id NOT IN ({keep})
            """
        )
        op.execute(
            f"DELETE FROM {table} WHERE id IN "
            f"(SELECT id FROM {ARCHIVE} WHERE source_table = '{table}')"
        )
        op.execute(f"UPDATE {table} SET sort_order = 0")
        op.drop_index(f"ix_{table}_{owner}", table_name=table)
        op.create_index(f"ix_{table}_{owner}", table, [owner], unique=True)


def downgrade() -> None:
    for table, owner, owner_table, has_active in TABLES:
        op.drop_index(f"ix_{table}_{owner}", table_name=table)
        op.create_index(f"ix_{table}_{owner}", table, [owner], unique=False)
        cols = f"id, {owner}, src, alt, {'is_active, ' if has_active else ''}sort_order"
        vals = (
            f"a.id, a.owner_id, a.src, a.alt, {'a.is_active, ' if has_active else ''}a.sort_order"
        )
        # Only restore photos whose owner still exists.
        op.execute(
            f"""
            INSERT INTO {table} ({cols}, created_at, updated_at)
            SELECT {vals}, a.created_at, now()
            FROM {ARCHIVE} a
            WHERE a.source_table = '{table}'
              AND EXISTS (SELECT 1 FROM {owner_table} o WHERE o.id = a.owner_id)
            """
        )
    op.drop_index(op.f(f"ix_{ARCHIVE}_source_table"), table_name=ARCHIVE)
    op.drop_table(ARCHIVE)
