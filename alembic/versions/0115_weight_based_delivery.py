"""Add weight-based delivery charge columns to products, variants, delivery_settings, and orders.

Revision ID: 0115
Revises: 0114
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0115"
down_revision: str | None = "0114"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. products.weight_grams
    op.add_column("products", sa.Column("weight_grams", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_products_weight_grams_non_negative"),
        "products",
        "weight_grams IS NULL OR weight_grams >= 0",
    )

    # 2. product_variants.weight_grams
    op.add_column("product_variants", sa.Column("weight_grams", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_product_variants_weight_grams_non_negative"),
        "product_variants",
        "weight_grams IS NULL OR weight_grams >= 0",
    )

    # 3. delivery_settings weight slab configuration
    op.add_column(
        "delivery_settings",
        sa.Column("weight_pricing_enabled", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "delivery_settings",
        sa.Column("base_weight_grams", sa.Integer(), server_default="1000", nullable=False),
    )
    op.add_column(
        "delivery_settings",
        sa.Column("extra_weight_step_grams", sa.Integer(), server_default="1000", nullable=False),
    )
    op.add_column(
        "delivery_settings",
        sa.Column("extra_fee_inside", sa.Integer(), server_default="20", nullable=False),
    )
    op.add_column(
        "delivery_settings",
        sa.Column("extra_fee_suburban", sa.Integer(), server_default="20", nullable=False),
    )
    op.add_column(
        "delivery_settings",
        sa.Column("extra_fee_outside", sa.Integer(), server_default="20", nullable=False),
    )
    op.add_column(
        "delivery_settings",
        sa.Column("packaging_weight_grams", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "delivery_settings",
        sa.Column(
            "default_product_weight_grams", sa.Integer(), server_default="500", nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_delivery_settings_weight_steps_positive"),
        "delivery_settings",
        "base_weight_grams >= 1 AND extra_weight_step_grams >= 1",
    )
    op.create_check_constraint(
        op.f("ck_delivery_settings_extra_fees_non_negative"),
        "delivery_settings",
        "extra_fee_inside >= 0 AND extra_fee_suburban >= 0 AND extra_fee_outside >= 0 "
        "AND packaging_weight_grams >= 0 AND default_product_weight_grams >= 0",
    )

    # 4. orders.total_weight_grams
    op.add_column("orders", sa.Column("total_weight_grams", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_orders_total_weight_non_negative"),
        "orders",
        "total_weight_grams IS NULL OR total_weight_grams >= 0",
    )

    # 5. order_items.unit_weight_grams
    op.add_column("order_items", sa.Column("unit_weight_grams", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_order_items_unit_weight_non_negative"),
        "order_items",
        "unit_weight_grams IS NULL OR unit_weight_grams >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_order_items_unit_weight_non_negative"), "order_items", type_="check"
    )
    op.drop_column("order_items", "unit_weight_grams")

    op.drop_constraint(op.f("ck_orders_total_weight_non_negative"), "orders", type_="check")
    op.drop_column("orders", "total_weight_grams")

    op.drop_constraint(
        op.f("ck_delivery_settings_extra_fees_non_negative"),
        "delivery_settings",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_delivery_settings_weight_steps_positive"),
        "delivery_settings",
        type_="check",
    )
    op.drop_column("delivery_settings", "default_product_weight_grams")
    op.drop_column("delivery_settings", "packaging_weight_grams")
    op.drop_column("delivery_settings", "extra_fee_outside")
    op.drop_column("delivery_settings", "extra_fee_suburban")
    op.drop_column("delivery_settings", "extra_fee_inside")
    op.drop_column("delivery_settings", "extra_weight_step_grams")
    op.drop_column("delivery_settings", "base_weight_grams")
    op.drop_column("delivery_settings", "weight_pricing_enabled")

    op.drop_constraint(
        op.f("ck_product_variants_weight_grams_non_negative"),
        "product_variants",
        type_="check",
    )
    op.drop_column("product_variants", "weight_grams")

    op.drop_constraint(
        op.f("ck_products_weight_grams_non_negative"),
        "products",
        type_="check",
    )
    op.drop_column("products", "weight_grams")
