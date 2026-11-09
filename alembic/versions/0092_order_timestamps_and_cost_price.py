"""Order delivery timestamps, an orders.status index, and product cost price

Revision ID: 0092
Revises: 0091
Create Date: 2026-11-09

Adds, all nullable:
 * orders.delivered_at, orders.returned_at (timestamptz)
 * products.cost_price numeric(12, 2), with CHECK cost_price IS NULL OR cost_price >= 0
 * ix_orders_status, unless an index that already leads with orders.status exists

Backfill uses the recorded status change, not a guess. There is no dedicated order-status
history table. The time is the earliest audit_events row with action ORDER_STATUS_CHANGED,
target_type order, and metadata.to of delivered or returned. Orders that are delivered or
returned but have no such row stay NULL. orders.created_at and orders.updated_at are never
copied. A returned order also receives delivered_at when a delivered event was recorded.

The UPDATE touches only the new timestamp column, and only where it is still NULL.

Downgrade drops the index this revision created (ix_orders_status), the check constraint,
and the three columns. It does not drop a differently named status index that was already
there, and it does not change any other column.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0092"
down_revision: str | None = "0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_INDEX = "ix_orders_status"
_COST_CHECK = "ck_products_cost_price_non_negative"

# Earliest recorded transition. Text compare avoids casting a bad target_id.
_DELIVERED_BACKFILL = sa.text(
    """
    UPDATE orders AS o
    SET delivered_at = hist.changed_at
    FROM (
        SELECT target_id, min(created_at) AS changed_at
        FROM audit_events
        WHERE action = 'ORDER_STATUS_CHANGED'
          AND target_type = 'order'
          AND metadata->>'to' = 'delivered'
        GROUP BY target_id
    ) AS hist
    WHERE o.delivered_at IS NULL
      AND o.status IN ('delivered', 'returned')
      AND o.id::text = hist.target_id
    """
)
_RETURNED_BACKFILL = sa.text(
    """
    UPDATE orders AS o
    SET returned_at = hist.changed_at
    FROM (
        SELECT target_id, min(created_at) AS changed_at
        FROM audit_events
        WHERE action = 'ORDER_STATUS_CHANGED'
          AND target_type = 'order'
          AND metadata->>'to' = 'returned'
        GROUP BY target_id
    ) AS hist
    WHERE o.returned_at IS NULL
      AND o.status = 'returned'
      AND o.id::text = hist.target_id
    """
)


def _leading_status_index(bind: sa.Connection) -> str | None:
    for index in sa.inspect(bind).get_indexes("orders"):
        columns = [str(name) for name in (index.get("column_names") or [])]
        if columns and columns[0] == "status":
            return str(index["name"])
    return None


def upgrade() -> None:
    op.add_column("orders", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("products", sa.Column("cost_price", sa.Numeric(12, 2), nullable=True))
    op.create_check_constraint(
        op.f(_COST_CHECK),
        "products",
        "cost_price IS NULL OR cost_price >= 0",
    )
    # 0005 indexes phone and created_at only. user_id has its own index. Nothing leads
    # with status, so this adds ix_orders_status. A pre-existing leading status index is left
    # alone.
    if _leading_status_index(op.get_bind()) is None:
        op.create_index(op.f(_STATUS_INDEX), "orders", ["status"], unique=False)
    op.execute(_DELIVERED_BACKFILL)
    op.execute(_RETURNED_BACKFILL)


def downgrade() -> None:
    bind = op.get_bind()
    names = {str(index["name"]) for index in sa.inspect(bind).get_indexes("orders")}
    if _STATUS_INDEX in names:
        op.drop_index(op.f(_STATUS_INDEX), table_name="orders")
    op.drop_constraint(op.f(_COST_CHECK), "products", type_="check")
    op.drop_column("products", "cost_price")
    op.drop_column("orders", "returned_at")
    op.drop_column("orders", "delivered_at")
