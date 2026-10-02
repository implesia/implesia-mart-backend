"""cash on delivery orders

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payment_method", sa.String(length=16), nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("district", sa.String(length=80), nullable=False),
        sa.Column("area", sa.String(length=120), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=False),
        sa.Column("delivery_zone", sa.String(length=16), nullable=False),
        sa.Column("subtotal", sa.Integer(), nullable=False),
        sa.Column("shipping", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("courier_name", sa.String(length=120), nullable=False),
        sa.Column("tracking_number", sa.String(length=120), nullable=False),
        sa.Column("inventory_held", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('new', 'confirmed', 'shipped', 'delivered', 'cancelled', 'returned')",
            name="ck_orders_status_known",
        ),
        sa.CheckConstraint("source IN ('cart', 'direct')", name="ck_orders_source_known"),
        sa.CheckConstraint(
            "subtotal >= 0 AND shipping >= 0 AND total >= 0",
            name="ck_orders_money_non_negative",
        ),
        sa.CheckConstraint("payment_method = 'cod'", name="ck_orders_payment_cod"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number", name="uq_orders_number"),
    )
    op.create_index("ix_orders_phone", "orders", ["phone"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("image_src", sa.String(length=2048), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "quantity >= 1 AND quantity <= 5",
            name="ck_order_items_quantity_in_range",
        ),
        sa.CheckConstraint(
            "unit_price >= 0 AND line_total >= 0",
            name="ck_order_items_money_non_negative",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_table(
        "order_idempotency",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_order_idempotency_key")),
    )


def downgrade() -> None:
    op.drop_table("order_idempotency")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_orders_phone", table_name="orders")
    op.drop_table("orders")
