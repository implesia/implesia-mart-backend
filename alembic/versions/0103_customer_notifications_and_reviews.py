"""customer avatar, notifications and product reviews

Revision ID: 0103
Revises: 0102
Create Date: 2026-11-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0103"
down_revision: str | None = "0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add avatar_url to users table
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))

    # 2. Create customer_notifications table
    op.create_table(
        "customer_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=32), server_default="order_status", nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("language", sa.String(length=8), server_default="bn", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_notifications_user_id_created_at",
        "customer_notifications",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_customer_notifications_user_id_is_read",
        "customer_notifications",
        ["user_id", "is_read"],
    )

    # 3. Create product_reviews table
    op.create_table(
        "product_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("headline", sa.String(length=160), server_default="", nullable=False),
        sa.Column("comment", sa.String(length=2000), server_default="", nullable=False),
        sa.Column(
            "is_verified_purchase", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_product_reviews_rating_range"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_reviews_product_id_is_published_created_at",
        "product_reviews",
        ["product_id", "is_published", "created_at"],
    )
    op.create_index(
        "ix_product_reviews_user_product",
        "product_reviews",
        ["user_id", "product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_reviews_user_product", table_name="product_reviews")
    op.drop_index(
        "ix_product_reviews_product_id_is_published_created_at", table_name="product_reviews"
    )
    op.drop_table("product_reviews")
    op.drop_index("ix_customer_notifications_user_id_is_read", table_name="customer_notifications")
    op.drop_index(
        "ix_customer_notifications_user_id_created_at", table_name="customer_notifications"
    )
    op.drop_table("customer_notifications")
    op.drop_column("users", "avatar_url")
