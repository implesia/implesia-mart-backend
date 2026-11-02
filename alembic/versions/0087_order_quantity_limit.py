"""admin-configurable maximum quantity per order line

Revision ID: 0087
Revises: 0086
Create Date: 2026-11-02

Adds:
- `pricing_settings.max_quantity` (default 10, 1 to 1000): the store-wide maximum of one
  product (or variant) per cart line / order line.
- Widens the product checks: `min_order_quantity` and a custom `max_order_quantity` may now go
  up to 1000 (was 5). `max_order_quantity` NULL now means "use the store-wide limit".
- Widens the `cart_items.quantity` and `order_items.quantity` checks from 1-5 to 1-1000.

What this does to existing data: nothing is rewritten. Every saved product limit (1 to 5)
stays valid. Products without their own limit follow the store-wide limit (10).

Rollback limits (downgrade): drops `max_quantity` and restores the old checks (max 5). The
downgrade fails if a product limit, cart line or order line is above 5; lower those first.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _product_checks(ceiling: int) -> None:
    op.create_check_constraint(
        op.f("ck_products_min_qty_range"),
        "products",
        f"min_order_quantity >= 1 AND min_order_quantity <= {ceiling}",
    )
    op.create_check_constraint(
        op.f("ck_products_max_qty_range"),
        "products",
        "max_order_quantity IS NULL OR "
        f"(max_order_quantity >= min_order_quantity AND max_order_quantity <= {ceiling})",
    )


def _drop_product_checks() -> None:
    op.drop_constraint(op.f("ck_products_max_qty_range"), "products", type_="check")
    op.drop_constraint(op.f("ck_products_min_qty_range"), "products", type_="check")


# Created by 0003/0005 with the naming convention applied twice.
_LINE_CHECKS = {
    "cart_items": "ck_cart_items_ck_cart_items_quantity_in_range",
    "order_items": "ck_order_items_ck_order_items_quantity_in_range",
}


def _line_checks(ceiling: int, drop: dict[str, str]) -> None:
    for table, old in drop.items():
        op.drop_constraint(op.f(old), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_quantity_in_range"),
            table,
            f"quantity >= 1 AND quantity <= {ceiling}",
        )


def upgrade() -> None:
    op.add_column(
        "pricing_settings",
        sa.Column("max_quantity", sa.Integer(), server_default="10", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_pricing_settings_max_quantity_range"),
        "pricing_settings",
        "max_quantity >= 1 AND max_quantity <= 1000",
    )
    _drop_product_checks()
    _product_checks(1000)
    _line_checks(1000, _LINE_CHECKS)


def downgrade() -> None:
    _line_checks(5, {table: f"ck_{table}_quantity_in_range" for table in _LINE_CHECKS})
    _drop_product_checks()
    _product_checks(5)
    op.drop_constraint(
        op.f("ck_pricing_settings_max_quantity_range"), "pricing_settings", type_="check"
    )
    op.drop_column("pricing_settings", "max_quantity")
