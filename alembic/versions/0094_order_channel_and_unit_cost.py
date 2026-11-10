"""Order channel and the cost snapshot on each order line

Revision ID: 0094
Revises: 0093
Create Date: 2026-11-10

Adds, both nullable, and does not update any existing row:

* orders.channel (varchar 32), indexed. Old orders stay NULL.
  New checkout orders are filled by the application with "website".
  There is no server default, so a read of an old row is NULL.
  orders.source and ck_orders_source_known are not changed.
* order_items.unit_cost numeric(12, 2), NULL or >= 0.
  Old lines stay NULL. The application copies products.cost_price
  when a new order is placed.

Also adds indexes on orders.delivered_at and orders.returned_at so
report filters do not scan the whole table. Those columns already exist.

Downgrade drops only the indexes, the check, and the two columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0094"
down_revision: str | None = "0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNEL_INDEX = "ix_orders_channel"
_DELIVERED_INDEX = "ix_orders_delivered_at"
_RETURNED_INDEX = "ix_orders_returned_at"
_COST_CHECK = "ck_order_items_unit_cost_non_negative"


def upgrade() -> None:
    op.add_column("orders", sa.Column("channel", sa.String(length=32), nullable=True))
    op.create_index(op.f(_CHANNEL_INDEX), "orders", ["channel"], unique=False)
    op.create_index(op.f(_DELIVERED_INDEX), "orders", ["delivered_at"], unique=False)
    op.create_index(op.f(_RETURNED_INDEX), "orders", ["returned_at"], unique=False)
    op.add_column("order_items", sa.Column("unit_cost", sa.Numeric(12, 2), nullable=True))
    op.create_check_constraint(
        op.f(_COST_CHECK),
        "order_items",
        "unit_cost IS NULL OR unit_cost >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_COST_CHECK), "order_items", type_="check")
    op.drop_column("order_items", "unit_cost")
    op.drop_index(op.f(_RETURNED_INDEX), table_name="orders")
    op.drop_index(op.f(_DELIVERED_INDEX), table_name="orders")
    op.drop_index(op.f(_CHANNEL_INDEX), table_name="orders")
    op.drop_column("orders", "channel")
