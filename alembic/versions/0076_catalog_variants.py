"""catalog variants: per-variant price and stock, order limits, cart and order links

Revision ID: 0076
Revises: 0075
Create Date: 2026-10-25

Purely additive (expand only). Nothing is dropped, renamed or rewritten, so every legacy
product, cart line and order keeps working unchanged.

1. `product_variants`: one row per purchasable combination of a product's option values,
   with its own price, compare-at price, stock, SKU and active flag. The database refuses a
   duplicate combination per product (`uq_product_variants_option_key`) and a duplicate SKU
   across the catalog (case-insensitive, empty SKUs exempt).
2. `products.has_variants` (default false) marks variant products; for them price,
   compare_at_price and quantity are a roll-up of the active variants. `min_order_quantity`
   (default 1) and `max_order_quantity` (NULL = platform cap of 5) are per-product limits.
   BACKFILL: the column defaults ARE the backfill. Every existing product becomes
   "no variants, order 1 to 5", which is exactly how it behaved before.
3. `cart_items.variant_id` (CASCADE) and `order_items.variant_id` (SET NULL) plus
   `order_items.sku` (a snapshot, default ''). Existing rows get NULL / ''.
4. The cart's one-line-per-product constraint becomes two partial unique indexes: one line
   per product when no variant, one line per variant otherwise.

Rollback limits (downgrade):
 - `product_variants` is dropped, so all variant rows (prices, stock, SKUs) are lost, and
   `order_items.variant_id` / `.sku` are lost. Order lines keep their own title, price,
   selection snapshot and totals, so order history stays readable.
 - Cart lines that point at a variant are deleted (they cannot exist without it).
 - Products keep the last rolled-up price and stock; their option lists in `content`
   are untouched, but the variant-specific prices are gone.
 Take a `pg_dump` before upgrading a real database.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_variants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("option_key", sa.String(length=400), nullable=False),
        sa.Column("sku", sa.String(length=64), server_default="", nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("compare_at_price", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("price >= 0", name=op.f("ck_product_variants_price_non_negative")),
        sa.CheckConstraint(
            "compare_at_price IS NULL OR compare_at_price >= price",
            name=op.f("ck_product_variants_compare_at_gte_price"),
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name=op.f("ck_product_variants_quantity_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_variants_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_variants")),
        sa.UniqueConstraint("product_id", "option_key", name="uq_product_variants_option_key"),
    )
    op.create_index(
        "uq_product_variants_sku",
        "product_variants",
        [sa.text("lower(sku)")],
        unique=True,
        postgresql_where=sa.text("sku <> ''"),
    )
    op.create_index("ix_product_variants_product", "product_variants", ["product_id", "sort_order"])

    op.add_column(
        "products",
        sa.Column("has_variants", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "products",
        sa.Column("min_order_quantity", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("products", sa.Column("max_order_quantity", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_products_min_qty_range"),
        "products",
        "min_order_quantity >= 1 AND min_order_quantity <= 5",
    )
    op.create_check_constraint(
        op.f("ck_products_max_qty_range"),
        "products",
        "max_order_quantity IS NULL OR "
        "(max_order_quantity >= min_order_quantity AND max_order_quantity <= 5)",
    )

    op.add_column("cart_items", sa.Column("variant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_cart_items_variant_id_product_variants"),
        "cart_items",
        "product_variants",
        ["variant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_cart_items_cart_product", "cart_items", type_="unique")
    op.create_index(
        "uq_cart_items_cart_product",
        "cart_items",
        ["cart_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("variant_id IS NULL"),
    )
    op.create_index(
        "uq_cart_items_cart_variant",
        "cart_items",
        ["cart_id", "variant_id"],
        unique=True,
        postgresql_where=sa.text("variant_id IS NOT NULL"),
    )

    op.add_column("order_items", sa.Column("variant_id", sa.Uuid(), nullable=True))
    op.add_column(
        "order_items", sa.Column("sku", sa.String(length=64), server_default="", nullable=False)
    )
    op.create_foreign_key(
        op.f("fk_order_items_variant_id_product_variants"),
        "order_items",
        "product_variants",
        ["variant_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_order_items_variant_id_product_variants"), "order_items", type_="foreignkey"
    )
    op.drop_column("order_items", "sku")
    op.drop_column("order_items", "variant_id")

    # A cart line for a variant cannot survive without variants.
    op.execute("DELETE FROM cart_items WHERE variant_id IS NOT NULL")
    op.drop_index("uq_cart_items_cart_variant", table_name="cart_items")
    op.drop_index("uq_cart_items_cart_product", table_name="cart_items")
    op.create_unique_constraint(
        "uq_cart_items_cart_product", "cart_items", ["cart_id", "product_id"]
    )
    op.drop_constraint(
        op.f("fk_cart_items_variant_id_product_variants"), "cart_items", type_="foreignkey"
    )
    op.drop_column("cart_items", "variant_id")

    op.drop_constraint(op.f("ck_products_max_qty_range"), "products", type_="check")
    op.drop_constraint(op.f("ck_products_min_qty_range"), "products", type_="check")
    op.drop_column("products", "max_order_quantity")
    op.drop_column("products", "min_order_quantity")
    op.drop_column("products", "has_variants")

    op.drop_index("ix_product_variants_product", table_name="product_variants")
    op.drop_index("uq_product_variants_sku", table_name="product_variants")
    op.drop_table("product_variants")
