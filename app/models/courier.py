"""Courier shipment tracking, webhook idempotency, and synced courier locations (Phase 23)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CourierShipment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "courier_shipments"
    __table_args__ = (
        CheckConstraint("cod_amount >= 0", name="cod_amount_non_negative"),
        Index(
            "uq_courier_shipments_consignment_id",
            "consignment_id",
            unique=True,
            postgresql_where=text("consignment_id IS NOT NULL"),
            sqlite_where=text("consignment_id IS NOT NULL"),
        ),
    )

    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        default="steadfast",
        server_default="steadfast",
        nullable=False,
        index=True,
    )
    invoice: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    consignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tracking_code: Mapped[str] = mapped_column(
        String(120),
        default="",
        server_default="",
        nullable=False,
        index=True,
    )
    cod_amount: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    delivery_status: Mapped[str] = mapped_column(
        String(64),
        default="in_review",
        server_default="in_review",
        nullable=False,
        index=True,
    )
    return_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_final: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    is_return_received: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    tracking_events: Mapped[list[Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=list,
        nullable=False,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    booked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_payment_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    settled_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=dict,
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<CourierShipment {self.provider}:{self.invoice} "
            f"(cid={self.consignment_id}, status={self.delivery_status})>"
        )


class CourierWebhookEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "courier_webhook_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_courier_webhook_events_event_key"),
    )

    provider: Mapped[str] = mapped_column(
        String(32),
        default="steadfast",
        server_default="steadfast",
        nullable=False,
        index=True,
    )
    event_key: Mapped[str] = mapped_column(String(200), nullable=False)
    consignment_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    invoice: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(
        String(64), default="", server_default="", nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=dict,
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CourierLocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "courier_locations"
    __table_args__ = (
        Index(
            "uq_courier_locations_provider_district_ps",
            "provider",
            "district",
            "police_station",
            unique=True,
        ),
    )

    provider: Mapped[str] = mapped_column(
        String(32),
        default="steadfast",
        server_default="steadfast",
        nullable=False,
    )
    district: Mapped[str] = mapped_column(String(120), nullable=False)
    police_station: Mapped[str] = mapped_column(String(160), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
