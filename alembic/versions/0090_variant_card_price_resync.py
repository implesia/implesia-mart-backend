"""re-sync the card price of variant products from their variants

Revision ID: 0090
Revises: 0089
Create Date: 2026-11-03

Saving a variant product in the dashboard without changing its variants sent
`compare_at_price: null` (and a summary `price`), and the API wrote those onto the product row.
The product cards read `products.price` / `products.compare_at_price`, so the struck-through
price and the -X% badge disappeared although the variants still had their compare-at prices.
The service is fixed in the same change; this repairs rows saved before it.

What this does to existing data: for products with variants only, `price` and
`compare_at_price` are set to the cheapest active variant's (lowest sort_order on a tie;
all variants when none is active), the same values every variant save writes. Variants,
plain products, orders and carts are not touched. Rows that already match are not updated.

Rollback limits (downgrade): nothing to undo; the values are derived from the variants.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0090"
down_revision: str | None = "0089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE products AS p
        SET price = v.price, compare_at_price = v.compare_at_price
        FROM (
            SELECT DISTINCT ON (product_id) product_id, price, compare_at_price
            FROM product_variants
            ORDER BY product_id, (NOT is_active), price, sort_order
        ) AS v
        WHERE p.id = v.product_id
          AND p.has_variants
          AND (p.price <> v.price OR p.compare_at_price IS DISTINCT FROM v.compare_at_price)
        """
    )


def downgrade() -> None:
    pass
