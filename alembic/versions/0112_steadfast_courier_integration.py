"""add steadfast courier operations tables and widen order_activities.action

Revision ID: 0112
Revises: 0111
Create Date: 2026-11-25

Additive-only:
* courier_shipments(id, order_id, provider, invoice, consignment_id, tracking_code,
  cod_amount, delivery_status, return_status, is_final, is_return_received,
  tracking_events, last_synced_at, booked_by_id, booked_at, settled_payment_id,
  settled_amount, settled_at, raw_payload, created_at, updated_at)
* courier_webhook_events(id, provider, event_key, consignment_id, invoice,
  event_type, payload, processed_at, created_at)
* courier_locations(id, provider, district, police_station, synced_at)
* Widens order_activities.action check to also allow 'courier_booked',
  'courier_webhook', and 'return_requested'.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0112"
down_revision: str | None = "0111"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ACTION_SQL = (
    "action IN ('created', 'status_changed', 'call_status_changed', "
    "'items_edited', 'courier_edited', 'printed', 'note_changed', "
    "'customer_message', 'payment_updated', 'courier_booked', "
    "'courier_webhook', 'return_requested')"
)
_OLD_ACTION_SQL = (
    "action IN ('created', 'status_changed', 'call_status_changed', "
    "'items_edited', 'courier_edited', 'printed', 'note_changed', "
    "'customer_message', 'payment_updated')"
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
        op.drop_constraint(op.f(existing), table, type_="check")
    op.create_check_constraint(op.f(name), table, sql)


def _json_type() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    json_col = _json_type()
    op.create_table(
        "courier_shipments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="steadfast"),
        sa.Column("invoice", sa.String(length=100), nullable=False),
        sa.Column("consignment_id", sa.String(length=64), nullable=True),
        sa.Column("tracking_code", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("cod_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "delivery_status", sa.String(length=64), nullable=False, server_default="in_review"
        ),
        sa.Column("return_status", sa.String(length=64), nullable=True),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "is_return_received", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("tracking_events", json_col, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "booked_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_payment_id", sa.String(length=64), nullable=True),
        sa.Column("settled_amount", sa.Integer(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", json_col, nullable=False, server_default=sa.text("'{}'")),
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
        sa.CheckConstraint("cod_amount >= 0", name="ck_courier_shipments_cod_amount_non_negative"),
    )
    op.create_index("ix_courier_shipments_order_id", "courier_shipments", ["order_id"])
    op.create_index("ix_courier_shipments_provider", "courier_shipments", ["provider"])
    op.create_index("ix_courier_shipments_invoice", "courier_shipments", ["invoice"])
    op.create_index("ix_courier_shipments_tracking_code", "courier_shipments", ["tracking_code"])
    op.create_index(
        "ix_courier_shipments_delivery_status", "courier_shipments", ["delivery_status"]
    )
    op.create_index("ix_courier_shipments_booked_by_id", "courier_shipments", ["booked_by_id"])
    op.create_index(
        "ix_courier_shipments_settled_payment_id", "courier_shipments", ["settled_payment_id"]
    )
    op.create_index(
        "uq_courier_shipments_consignment_id",
        "courier_shipments",
        ["consignment_id"],
        unique=True,
        postgresql_where=sa.text("consignment_id IS NOT NULL"),
        sqlite_where=sa.text("consignment_id IS NOT NULL"),
    )

    op.create_table(
        "courier_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="steadfast"),
        sa.Column("event_key", sa.String(length=200), nullable=False),
        sa.Column("consignment_id", sa.String(length=64), nullable=True),
        sa.Column("invoice", sa.String(length=100), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("payload", json_col, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("event_key", name="uq_courier_webhook_events_event_key"),
    )
    op.create_index("ix_courier_webhook_events_provider", "courier_webhook_events", ["provider"])
    op.create_index(
        "ix_courier_webhook_events_consignment_id", "courier_webhook_events", ["consignment_id"]
    )
    op.create_index("ix_courier_webhook_events_invoice", "courier_webhook_events", ["invoice"])

    op.create_table(
        "courier_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="steadfast"),
        sa.Column("district", sa.String(length=120), nullable=False),
        sa.Column("police_station", sa.String(length=160), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_courier_locations_provider_district_ps",
        "courier_locations",
        ["provider", "district", "police_station"],
        unique=True,
    )

    if op.get_bind().dialect.name == "postgresql":
        _replace_check(
            "order_activities",
            "'printed'",
            "ck_order_activities_action_known",
            _NEW_ACTION_SQL,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        added = bind.scalar(
            sa.text(
                "SELECT count(*) FROM order_activities "
                "WHERE action IN ('courier_booked', 'courier_webhook', 'return_requested')"
            )
        )
        if added:
            raise RuntimeError(
                f"{added} courier activity row(s) exist; "
                "downgrade would break the activity check."
            )
        _replace_check(
            "order_activities",
            "'printed'",
            "ck_order_activities_action_known",
            _OLD_ACTION_SQL,
        )

    op.drop_index("uq_courier_locations_provider_district_ps", table_name="courier_locations")
    op.drop_table("courier_locations")

    op.drop_index("ix_courier_webhook_events_invoice", table_name="courier_webhook_events")
    op.drop_index("ix_courier_webhook_events_consignment_id", table_name="courier_webhook_events")
    op.drop_index("ix_courier_webhook_events_provider", table_name="courier_webhook_events")
    op.drop_table("courier_webhook_events")

    op.drop_index("uq_courier_shipments_consignment_id", table_name="courier_shipments")
    op.drop_index("ix_courier_shipments_settled_payment_id", table_name="courier_shipments")
    op.drop_index("ix_courier_shipments_booked_by_id", table_name="courier_shipments")
    op.drop_index("ix_courier_shipments_delivery_status", table_name="courier_shipments")
    op.drop_index("ix_courier_shipments_tracking_code", table_name="courier_shipments")
    op.drop_index("ix_courier_shipments_invoice", table_name="courier_shipments")
    op.drop_index("ix_courier_shipments_provider", table_name="courier_shipments")
    op.drop_index("ix_courier_shipments_order_id", table_name="courier_shipments")
    op.drop_table("courier_shipments")
