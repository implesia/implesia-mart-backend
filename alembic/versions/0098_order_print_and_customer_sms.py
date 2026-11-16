"""Print lookup index and customer SMS claims

Revision ID: 0098
Revises: 0097
Create Date: 2026-11-16

Adds nullable columns and one index. Does not update any existing order
row: totals, statuses, and dates stay as they are. The new columns stay
NULL on those rows.

* orders.customer_sms_confirmed_at timestamptz NULL
* orders.customer_sms_shipped_at timestamptz NULL
* ix_orders_tracking_number_lower on lower(tracking_number)

Widens order_activities.action to allow 'customer_message'. Existing
action values stay valid.

Downgrade refuses while any activity row uses customer_message, because
the previous check would reject those rows. It then restores that check
and drops only the new index and columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0098"
down_revision: str | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ACTION_SQL = (
    "action IN ('created', 'status_changed', 'call_status_changed', "
    "'items_edited', 'courier_edited', 'printed', 'note_changed', "
    "'customer_message')"
)
_OLD_ACTION_SQL = (
    "action IN ('created', 'status_changed', 'call_status_changed', "
    "'items_edited', 'courier_edited', 'printed', 'note_changed')"
)


def _checks(table: str, needle: str) -> list[str]:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT con.conname FROM pg_constraint con "
                "JOIN pg_class rel ON rel.oid = con.conrelid "
                "WHERE rel.relname = :table AND con.contype = 'c' "
                "AND pg_get_constraintdef(con.oid) ILIKE :needle"
            ),
            {"table": table, "needle": f"%{needle}%"},
        )
        .fetchall()
    )
    return [row[0] for row in rows]


def _replace_check(table: str, needle: str, name: str, sql: str) -> None:
    for existing in _checks(table, needle):
        op.drop_constraint(existing, table, type_="check")
    op.create_check_constraint(op.f(name), table, sql)


def widen_activity_check() -> None:
    """Allow customer_message. Safe to run again: it drops and recreates the check."""
    _replace_check(
        "order_activities",
        "'printed'",
        "ck_order_activities_action_known",
        _NEW_ACTION_SQL,
    )


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("customer_sms_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("customer_sms_shipped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("CREATE INDEX ix_orders_tracking_number_lower ON orders (lower(tracking_number))")
    widen_activity_check()


def downgrade() -> None:
    bind = op.get_bind()
    sent = bind.scalar(
        sa.text("SELECT count(*) FROM order_activities WHERE action = 'customer_message'")
    )
    if sent:
        raise RuntimeError(
            f"{sent} customer message activity row(s) exist; "
            "downgrade would break the activity check."
        )
    _replace_check(
        "order_activities",
        "'printed'",
        "ck_order_activities_action_known",
        _OLD_ACTION_SQL,
    )
    op.execute("DROP INDEX IF EXISTS ix_orders_tracking_number_lower")
    op.drop_column("orders", "customer_sms_shipped_at")
    op.drop_column("orders", "customer_sms_confirmed_at")
