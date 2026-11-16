"""Coupons, redemptions, and the order snapshot of a coupon

Revision ID: 0096
Revises: 0095
Create Date: 2026-11-10

Adds coupons, coupon_products, coupon_categories, and coupon_redemptions.
Adds nullable orders.coupon_code and orders.coupon_discount.

No existing row is updated. Orders placed before this revision stay NULL
in both new columns, and their totals are not rewritten.

Downgrade drops only the new tables, the check, and the two columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0096"
down_revision: str | None = "0095"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DISCOUNT_CHECK = "ck_orders_coupon_discount_non_negative"


def upgrade() -> None:
    op.create_table(
        "coupons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("discount_type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Numeric(12, 2), nullable=False),
        sa.Column("max_discount", sa.Integer(), nullable=True),
        sa.Column("min_order_amount", sa.Integer(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("usage_limit_total", sa.Integer(), nullable=True),
        sa.Column("usage_limit_per_phone", sa.Integer(), nullable=True),
        sa.Column(
            "first_order_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "free_delivery",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "discount_type IN ('percent', 'fixed')",
            name="ck_coupons_discount_type_known",
        ),
        sa.CheckConstraint("value >= 0", name="ck_coupons_value_non_negative"),
        sa.CheckConstraint(
            "discount_type <> 'percent' OR value <= 100",
            name="ck_coupons_percent_at_most_100",
        ),
        sa.CheckConstraint(
            "discount_type <> 'fixed' OR max_discount IS NULL",
            name="ck_coupons_fixed_has_no_cap",
        ),
        sa.CheckConstraint(
            "max_discount IS NULL OR max_discount >= 1",
            name="ck_coupons_max_discount_positive",
        ),
        sa.CheckConstraint(
            "min_order_amount IS NULL OR min_order_amount >= 1",
            name="ck_coupons_min_order_positive",
        ),
        sa.CheckConstraint(
            "usage_limit_total IS NULL OR usage_limit_total >= 1",
            name="ck_coupons_total_limit_positive",
        ),
        sa.CheckConstraint(
            "usage_limit_per_phone IS NULL OR usage_limit_per_phone >= 1",
            name="ck_coupons_phone_limit_positive",
        ),
        sa.CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at >= starts_at",
            name="ck_coupons_window_ordered",
        ),
        sa.CheckConstraint(
            "length(code) >= 3 AND length(code) <= 32",
            name="ck_coupons_code_length",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_coupons_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_coupons"),
    )
    op.create_index(
        "uq_coupons_code_lower",
        "coupons",
        [sa.text("lower(code)")],
        unique=True,
    )
    op.create_index("ix_coupons_created_by", "coupons", ["created_by"])
    op.create_table(
        "coupon_products",
        sa.Column("coupon_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["coupon_id"],
            ["coupons.id"],
            name="fk_coupon_products_coupon_id_coupons",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_coupon_products_product_id_products",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("coupon_id", "product_id", name="pk_coupon_products"),
    )
    op.create_index("ix_coupon_products_product_id", "coupon_products", ["product_id"])
    op.create_table(
        "coupon_categories",
        sa.Column("coupon_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["coupon_id"],
            ["coupons.id"],
            name="fk_coupon_categories_coupon_id_coupons",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_coupon_categories_category_id_categories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("coupon_id", "category_id", name="pk_coupon_categories"),
    )
    op.create_index(
        "ix_coupon_categories_category_id", "coupon_categories", ["category_id"]
    )
    op.create_table(
        "coupon_redemptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("coupon_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("discount_amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'cancelled')",
            name="ck_coupon_redemptions_status_known",
        ),
        sa.CheckConstraint(
            "discount_amount >= 0",
            name="ck_coupon_redemptions_discount_non_negative",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND cancelled_at IS NOT NULL)",
            name="ck_coupon_redemptions_cancel_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["coupon_id"],
            ["coupons.id"],
            name="fk_coupon_redemptions_coupon_id_coupons",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_coupon_redemptions_order_id_orders",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_coupon_redemptions"),
        sa.UniqueConstraint("order_id", name="uq_coupon_redemptions_order_id"),
    )
    op.create_index(
        "ix_coupon_redemptions_coupon_id",
        "coupon_redemptions",
        ["coupon_id"],
    )
    op.create_index(
        "ix_coupon_redemptions_coupon_phone",
        "coupon_redemptions",
        ["coupon_id", "phone"],
    )
    op.create_index(
        "ix_coupon_redemptions_created_at",
        "coupon_redemptions",
        ["created_at"],
    )
    op.add_column("orders", sa.Column("coupon_code", sa.String(length=32), nullable=True))
    op.add_column("orders", sa.Column("coupon_discount", sa.Integer(), nullable=True))
    op.create_check_constraint(
        _DISCOUNT_CHECK,
        "orders",
        "coupon_discount IS NULL OR coupon_discount >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(_DISCOUNT_CHECK, "orders", type_="check")
    op.drop_column("orders", "coupon_discount")
    op.drop_column("orders", "coupon_code")
    op.drop_index("ix_coupon_redemptions_created_at", table_name="coupon_redemptions")
    op.drop_index("ix_coupon_redemptions_coupon_phone", table_name="coupon_redemptions")
    op.drop_index("ix_coupon_redemptions_coupon_id", table_name="coupon_redemptions")
    op.drop_table("coupon_redemptions")
    op.drop_index("ix_coupon_categories_category_id", table_name="coupon_categories")
    op.drop_table("coupon_categories")
    op.drop_index("ix_coupon_products_product_id", table_name="coupon_products")
    op.drop_table("coupon_products")
    op.drop_index("uq_coupons_code_lower", table_name="coupons")
    op.drop_index("ix_coupons_created_by", table_name="coupons")
    op.drop_table("coupons")
