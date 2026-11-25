"""Pydantic v2 schemas for Steadfast Merchant API & Courier Operations (Phase 23)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SteadfastPingResponse(BaseModel):
    configured: bool
    ok: bool
    balance: float | None = None
    circuit_open: bool = False
    circuit_retry_after_seconds: int = 0
    consecutive_auth_failures: int = 0
    error: str | None = None


class CourierShipmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID | None = None
    provider: str
    invoice: str
    consignment_id: str | None = None
    tracking_code: str
    cod_amount: int
    delivery_status: str
    return_status: str | None = None
    is_final: bool
    is_return_received: bool
    tracking_events: list[Any] = Field(default_factory=list)
    last_synced_at: datetime | None = None
    booked_by_id: uuid.UUID | None = None
    booked_at: datetime | None = None
    settled_payment_id: str | None = None
    settled_amount: int | None = None
    settled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BookOrderRequest(BaseModel):
    note: str | None = Field(default=None, max_length=480)
    cod_amount_override: int | None = Field(default=None, ge=0, le=10_000_000)
    recipient_name: str | None = Field(default=None, max_length=100)
    recipient_phone: str | None = Field(default=None, max_length=40)
    recipient_address: str | None = Field(default=None, max_length=490)
    delivery_type: int | None = Field(default=None, ge=0, le=1)


class BulkBookOrdersRequest(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=480)


class BulkBookOrderItemResult(BaseModel):
    order_id: uuid.UUID
    order_number: str | None = None
    status: Literal["booked", "skipped", "error"]
    shipment: CourierShipmentRead | None = None
    errors: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class BulkBookOrdersResponse(BaseModel):
    requested: int
    booked: int
    skipped: int
    failed: int
    results: list[BulkBookOrderItemResult]


class RefreshStatusResponse(BaseModel):
    shipment: CourierShipmentRead
    order_status: str | None = None
    cooldown_cached: bool = False
    tracking_events: list[dict[str, Any]] = Field(default_factory=list)


class OrderTrackingResponse(BaseModel):
    shipment: CourierShipmentRead
    tracking_events: list[dict[str, Any]] = Field(default_factory=list)
    cached: bool = False


class PickupRequestCreate(BaseModel):
    address: str | None = Field(default=None, max_length=490)
    phone: str | None = Field(default=None, max_length=40)
    note: str = Field(default="", max_length=480)


class PickupRequestResponse(BaseModel):
    ok: bool = True
    raw: dict[str, Any] = Field(default_factory=dict)


class ReturnRequestCreate(BaseModel):
    order_id: uuid.UUID | None = None
    consignment_id: str | None = Field(default=None, max_length=64)
    invoice: str | None = Field(default=None, max_length=100)
    tracking_code: str | None = Field(default=None, max_length=120)
    reason: str = Field(default="", max_length=480)


class ReturnRequestResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


class SteadfastOverviewResponse(BaseModel):
    balance: float | None = None
    parcel_states: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, Any] | None = None
    cached: bool = False


class SyncLocationsResponse(BaseModel):
    provider: str = "steadfast"
    synced_count: int
    districts_count: int
    synced_at: datetime


class DeliveryDistrictLocations(BaseModel):
    name: str
    areas: list[str]


class DeliveryLocationsResponse(BaseModel):
    provider: str = "steadfast"
    districts: list[DeliveryDistrictLocations] = Field(default_factory=list)
    total_areas: int = 0


# ---------------------------------------------------------------------------
# Phase 24 — Webhooks & Superadmin Finance Reconciliation
# ---------------------------------------------------------------------------


class SteadfastWebhookResponse(BaseModel):
    ok: bool = True
    status: Literal["processed", "duplicate", "ignored"] = "processed"
    event_key: str
    order_number: str | None = None
    order_status: str | None = None
    delivery_status: str | None = None
    return_status: str | None = None
    is_return_received: bool = False


class SteadfastBalanceResponse(BaseModel):
    current_balance: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SteadfastPaymentsListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    pages: int = 0


class ReconcileMatchedOrder(BaseModel):
    order_id: uuid.UUID
    order_number: str
    shipment_id: uuid.UUID | None = None
    consignment_id: str | None = None
    order_total: int
    paid_before: int
    due_before: int
    settled_amount: int
    already_reconciled: bool = False
    settled_payment_id: str | None = None


class SteadfastPaymentDetailResponse(BaseModel):
    payment: dict[str, Any] = Field(default_factory=dict)
    matched_orders: list[ReconcileMatchedOrder] = Field(default_factory=list)
    unmatched_parcels: list[dict[str, Any]] = Field(default_factory=list)
    already_reconciled_count: int = 0
    pending_reconcile_count: int = 0


class SteadfastReconcileResponse(BaseModel):
    payment_id: str
    reconciled_count: int = 0
    already_reconciled_count: int = 0
    unmatched_count: int = 0
    total_amount_applied: int = 0
    matched_orders: list[ReconcileMatchedOrder] = Field(default_factory=list)
    unmatched_parcels: list[dict[str, Any]] = Field(default_factory=list)
