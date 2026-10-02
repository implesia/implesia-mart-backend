"""catalog products

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=300), server_default="", nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("compare_at_price", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("badge", sa.String(length=32), nullable=True),
        sa.Column("image_src", sa.String(length=2048), server_default="", nullable=False),
        sa.Column("image_alt", sa.String(length=300), server_default="", nullable=False),
        sa.Column("unit_label", sa.String(length=40), server_default="", nullable=False),
        sa.Column("featured", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("published", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("price >= 0", name=op.f("ck_products_price_non_negative")),
        sa.CheckConstraint(
            "compare_at_price IS NULL OR compare_at_price >= price",
            name=op.f("ck_products_compare_at_gte_price"),
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name=op.f("ck_products_quantity_non_negative"),
        ),
        sa.CheckConstraint(
            "category IN ('gadgets', 'fashion')",
            name=op.f("ck_products_category_known"),
        ),
        sa.CheckConstraint(
            "status IN ('available', 'sold-out', 'coming-soon')",
            name=op.f("ck_products_status_known"),
        ),
        sa.CheckConstraint(
            "badge IS NULL OR badge IN ('New', 'Best Seller', 'Limited')",
            name=op.f("ck_products_badge_known"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("slug", name=op.f("uq_products_slug")),
    )
    op.create_index(
        op.f("ix_products_storefront"),
        "products",
        ["published", "category", "status", "price"],
        unique=False,
    )
    op.create_index(
        op.f("ix_products_featured"),
        "products",
        ["published", "featured"],
        unique=False,
    )
    op.create_index(op.f("ix_products_sort_order"), "products", ["sort_order"], unique=False)
    op.create_index(op.f("ix_products_created_at"), "products", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_products_created_at"), table_name="products")
    op.drop_index(op.f("ix_products_sort_order"), table_name="products")
    op.drop_index(op.f("ix_products_featured"), table_name="products")
    op.drop_index(op.f("ix_products_storefront"), table_name="products")
    op.drop_table("products")
