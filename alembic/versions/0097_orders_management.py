"""Orders management: packed status, origin, call status, activity log

Revision ID: 0097
Revises: 0096
Create Date: 2026-11-16

Adds columns and one table. Does not update subtotal, shipping, total,
coupon_discount, or any existing status value.

* orders.origin varchar(16) NOT NULL DEFAULT 'online'
* orders.call_status varchar(16) NOT NULL DEFAULT 'not_called'
* orders.manual_discount integer NOT NULL DEFAULT 0
* orders.paid_amount integer NOT NULL DEFAULT 0
* orders.printed_at timestamptz NULL
* orders.ordered_at timestamptz NULL
* order_activities (new table)

Widens the status check to allow 'packed' and the payment check to allow
cash, bkash, nagad, card, and due. Existing values stay valid.

orders.source (cart/direct) is not changed.

Downgrade refuses while any order uses packed or a new payment method,
because the old checks would reject those rows. It then drops only the
new table, checks, indexes, and columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0097"
down_revision: str | None = "0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_SQL = (
    "status IN ('new', 'confirmed', 'packed', 'shipped', 'delivered', 'cancelled', 'returned')"
)
_OLD_STATUS_SQL = (
    "status IN ('new', 'confirmed', 'shipped', 'delivered', 'cancelled', 'returned')"
)
_PAYMENT_SQL = (
    "payment_method IN ('cod', 'bangla_qr', 'cash', 'bkash', 'nagad', 'card', 'due')"
)
_OLD_PAYMENT_SQL = "payment_method IN ('cod', 'bangla_qr')"


def _checks(table: str, needle: str) -> list[str]:
    # Postgres stores `IN (...)` as `= ANY (ARRAY[...])`, so match a value
    # that only this check contains.
    rows = op.get_bind().execute(
        sa.text(
            "SELECT con.conname FROM pg_constraint con "
            "JOIN pg_class rel ON rel.oid = con.conrelid "
            "WHERE rel.relname = :table AND con.contype = 'c' "
            "AND pg_get_constraintdef(con.oid) ILIKE :needle"
        ),
        {"table": table, "needle": f"%{needle}%"},
    ).fetchall()
    return [row[0] for row in rows]


def _drop_if_present(table: str, name: str) -> None:
    found = op.get_bind().scalar(
        sa.text(
            "SELECT 1 FROM pg_constraint "
            "WHERE conrelid = (:table)::regclass AND conname = :name"
        ),
        {"table": table, "name": name},
    )
    if found:
        op.drop_constraint(op.f(name), table, type_="check")


def _replace_check(table: str, needle: str, name: str, sql: str) -> None:
    for existing in _checks(table, needle):
        op.drop_constraint(op.f(existing), table, type_="check")
    _drop_if_present(table, name)
    # op.f keeps the name we pass. A bare name would be prefixed again.
    op.create_check_constraint(op.f(name), table, sql)


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("origin", sa.String(length=16), nullable=False, server_default="online"),
    )
    op.add_column(
        "orders",
        sa.Column(
            "call_status", sa.String(length=16), nullable=False, server_default="not_called"
        ),
    )
    op.add_column(
        "orders",
        sa.Column("manual_discount", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "orders",
        sa.Column("paid_amount", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("orders", sa.Column("printed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_orders_origin"), "orders", ["origin"], unique=False)
    op.create_index(op.f("ix_orders_call_status"), "orders", ["call_status"], unique=False)
    op.create_index(op.f("ix_orders_ordered_at"), "orders", ["ordered_at"], unique=False)
    _replace_check("orders", "'shipped'", "ck_orders_status_known", _STATUS_SQL)
    _replace_check("orders", "'bangla_qr'", "ck_orders_payment_known", _PAYMENT_SQL)
    op.create_check_constraint(
        op.f("ck_orders_origin_known"), "orders", "origin IN ('online', 'offline')"
    )
    op.create_check_constraint(
        op.f("ck_orders_call_status_known"),
        "orders",
        "call_status IN ('not_called', 'confirmed', 'no_answer', 'fake')",
    )
    op.create_check_constraint(
        op.f("ck_orders_manual_discount_non_negative"), "orders", "manual_discount >= 0"
    )
    op.create_check_constraint(
        op.f("ck_orders_paid_non_negative"), "orders", "paid_amount >= 0"
    )
    op.create_table(
        "order_activities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.String(length=200), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "action IN ('created', 'status_changed', 'call_status_changed', "
            "'items_edited', 'courier_edited', 'printed', 'note_changed')",
            name=op.f("ck_order_activities_action_known"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            ondelete="CASCADE",
            name=op.f("fk_order_activities_order_id_orders"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name=op.f("fk_order_activities_actor_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_activities")),
    )
    op.create_index(
        "ix_order_activities_order_id_created_at",
        "order_activities",
        ["order_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_activities_actor_user_id"),
        "order_activities",
        ["actor_user_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    packed = bind.scalar(sa.text("SELECT count(*) FROM orders WHERE status = 'packed'"))
    if packed:
        raise RuntimeError(
            f"{packed} order(s) are packed; downgrading would break the status check."
        )
    other = bind.scalar(
        sa.text(
            "SELECT count(*) FROM orders "
            "WHERE payment_method NOT IN ('cod', 'bangla_qr')"
        )
    )
    if other:
        raise RuntimeError(
            f"{other} order(s) use an offline payment method; downgrade would break the check."
        )
    op.drop_index("ix_order_activities_order_id_created_at", table_name="order_activities")
    op.drop_table("order_activities")
    for name in (
        "ck_orders_paid_non_negative",
        "ck_orders_manual_discount_non_negative",
        "ck_orders_call_status_known",
        "ck_orders_origin_known",
    ):
        op.drop_constraint(op.f(name), "orders", type_="check")
    _replace_check("orders", "'bangla_qr'", "ck_orders_payment_known", _OLD_PAYMENT_SQL)
    _replace_check("orders", "'shipped'", "ck_orders_status_known", _OLD_STATUS_SQL)
    op.drop_index(op.f("ix_orders_ordered_at"), table_name="orders")
    op.drop_index(op.f("ix_orders_call_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_origin"), table_name="orders")
    op.drop_column("orders", "ordered_at")
    op.drop_column("orders", "printed_at")
    op.drop_column("orders", "paid_amount")
    op.drop_column("orders", "manual_discount")
    op.drop_column("orders", "call_status")
    op.drop_column("orders", "origin")
