"""custom product badges

Revision ID: 0084
Revises: 0083
Create Date: 2026-11-01

Creates `badges` (admin-managed badges: name, slug, tone, active flag, built-in flag) and
`product_badges` (which badges each product shows, in order).

What this does to existing data:
 * Seeds the three built-in badges that used to be fixed choices: "New" (slug `new`),
   "Best Seller" (`best-seller`) and "Limited" (`limited`), all active and marked built-in.
 * For every product whose `products.badge` is set, links the matching built-in badge, so
   every product keeps showing exactly the badge it had.
 * `products.badge` itself is NOT changed or dropped. It stays the column catalog ranking,
   the "new" view and the `badge` filter read; the API now keeps it in step with the
   built-in badges a product carries.

Rollback limits (downgrade): drops both tables. `products.badge` is untouched, so the old
single badge per product keeps working. Custom badges, their names and tones, and every
product-to-badge link (including extra badges added after upgrading) are lost.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0084"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SYSTEM = (
    ("new", "New", "primary"),
    ("best-seller", "Best Seller", "gold"),
    ("limited", "Limited", "primary"),
)


def upgrade() -> None:
    op.create_table(
        "badges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("slug", sa.String(length=48), nullable=False),
        sa.Column("tone", sa.String(length=16), server_default="primary", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "tone IN ('primary', 'gold', 'dark', 'alert', 'soft', 'soft-gold')",
            name=op.f("ck_badges_tone_known"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_badges")),
        sa.UniqueConstraint("slug", name=op.f("uq_badges_slug")),
    )
    op.create_index("uq_badges_name_lower", "badges", [sa.text("lower(name)")], unique=True)

    op.create_table(
        "product_badges",
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("badge_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_badges_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["badge_id"],
            ["badges.id"],
            name=op.f("fk_product_badges_badge_id_badges"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("product_id", "badge_id", name=op.f("pk_product_badges")),
    )
    op.create_index("ix_product_badges_badge_id", "product_badges", ["badge_id"])

    badges = sa.table(
        "badges",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("tone", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("is_system", sa.Boolean()),
    )
    op.bulk_insert(
        badges,
        [
            {
                "id": uuid.uuid4(),
                "name": name,
                "slug": slug,
                "tone": tone,
                "is_active": True,
                "is_system": True,
            }
            for slug, name, tone in _SYSTEM
        ],
    )
    # Every product keeps the badge it already had.
    op.execute(
        """
        INSERT INTO product_badges (product_id, badge_id, sort_order)
        SELECT p.id, b.id, 0
        FROM products AS p
        JOIN badges AS b ON b.is_system AND b.name = p.badge
        WHERE p.badge IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_product_badges_badge_id", table_name="product_badges")
    op.drop_table("product_badges")
    op.drop_index("uq_badges_name_lower", table_name="badges")
    op.drop_table("badges")
