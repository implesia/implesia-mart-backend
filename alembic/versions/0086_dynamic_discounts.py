"""dynamic discounts: base discount, quantity tiers and order price snapshots

Revision ID: 0086
Revises: 0085
Create Date: 2026-11-02

Adds:
- `pricing_settings` (one row, id 1): global quantity tiers, an on/off switch and the maximum
  total discount. Seeded with the default tiers (2: +0.25 %, 3: +0.5 %, 4: +0.75 %, 5: +1 %,
  6: +1.25 %, 7: +1.5 %, 8+: +2 %), switched on, maximum 90 %.
- `products.base_discount` (hundredths of a percent, NULL = derived from the two prices),
  `products.tier_mode` ('global' | 'custom', default 'global') and `products.tiers` (JSON, []).
- `order_items.regular_price`, `base_discount`, `quantity_discount`, `total_discount`
  (nullable price snapshot; older orders keep NULL).

What this does to existing data: nothing is rewritten. Every product keeps its `price` and
`compare_at_price`, gets base_discount NULL (its base % is derived from those two prices, so
the quantity-1 price is unchanged) and follows the global tiers. Existing orders are untouched.

Rollback limits (downgrade): drops the new columns and the settings table, so saved base
percentages, custom tiers, the global tier settings and order discount snapshots are lost.
Prices, totals and order lines stay as they are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0086"
down_revision: str | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
_DEFAULT_TIERS = (
    '[{"min_quantity": 2, "extra": 25}, {"min_quantity": 3, "extra": 50}, '
    '{"min_quantity": 4, "extra": 75}, {"min_quantity": 5, "extra": 100}, '
    '{"min_quantity": 6, "extra": 125}, {"min_quantity": 7, "extra": 150}, '
    '{"min_quantity": 8, "extra": 200}]'
)


def upgrade() -> None:
    op.create_table(
        "pricing_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tiers_enabled", sa.Boolean(), nullable=False),
        sa.Column("max_discount", sa.Integer(), nullable=False),
        sa.Column("tiers", _JSON, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_pricing_settings_singleton")),
        sa.CheckConstraint(
            "max_discount >= 0 AND max_discount <= 9999",
            name=op.f("ck_pricing_settings_max_discount_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_settings")),
    )
    op.get_bind().execute(
        sa.text(
            "INSERT INTO pricing_settings (id, tiers_enabled, max_discount, tiers) "
            "VALUES (1, true, 9000, CAST(:tiers AS JSONB))"
        ),
        {"tiers": _DEFAULT_TIERS},
    )

    op.add_column("products", sa.Column("base_discount", sa.Integer(), nullable=True))
    op.add_column(
        "products",
        sa.Column("tier_mode", sa.String(length=16), server_default="global", nullable=False),
    )
    op.add_column("products", sa.Column("tiers", _JSON, server_default="[]", nullable=False))
    op.create_check_constraint(
        op.f("ck_products_base_discount_range"),
        "products",
        "base_discount IS NULL OR (base_discount >= 0 AND base_discount <= 9999)",
    )
    op.create_check_constraint(
        op.f("ck_products_tier_mode_known"), "products", "tier_mode IN ('global', 'custom')"
    )

    for column in ("regular_price", "base_discount", "quantity_discount", "total_discount"):
        op.add_column("order_items", sa.Column(column, sa.Integer(), nullable=True))


def downgrade() -> None:
    for column in ("total_discount", "quantity_discount", "base_discount", "regular_price"):
        op.drop_column("order_items", column)
    op.drop_constraint(op.f("ck_products_tier_mode_known"), "products", type_="check")
    op.drop_constraint(op.f("ck_products_base_discount_range"), "products", type_="check")
    op.drop_column("products", "tiers")
    op.drop_column("products", "tier_mode")
    op.drop_column("products", "base_discount")
    op.drop_table("pricing_settings")
