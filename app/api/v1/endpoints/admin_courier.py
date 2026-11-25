"""Admin Courier Operations endpoints for Steadfast Merchant API (Phase 23)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query

from app.api.deps import DbSession, RequireSuperadmin, no_store, require_module_access
from app.models.user import User
from app.schemas.courier import (
    BookOrderRequest,
    BulkBookOrdersRequest,
    BulkBookOrdersResponse,
    CourierShipmentRead,
    OrderTrackingResponse,
    PickupRequestCreate,
    PickupRequestResponse,
    RefreshStatusResponse,
    ReturnRequestCreate,
    ReturnRequestResponse,
    SteadfastBalanceResponse,
    SteadfastOverviewResponse,
    SteadfastPaymentDetailResponse,
    SteadfastPaymentsListResponse,
    SteadfastPingResponse,
    SteadfastReconcileResponse,
    SyncLocationsResponse,
)
from app.services.courier import steadfast_finance_service, steadfast_service

router = APIRouter(dependencies=[Depends(no_store)])

RequireOrdersRead = Annotated[User, Depends(require_module_access("orders", "read"))]
RequireOrdersWrite = Annotated[User, Depends(require_module_access("orders", "write"))]


@router.get("/steadfast/ping", response_model=SteadfastPingResponse)
async def ping_steadfast(_staff: RequireOrdersRead) -> SteadfastPingResponse:
    return await steadfast_service.ping_steadfast()


@router.post("/steadfast/orders/{order_id}/book", response_model=CourierShipmentRead)
async def book_steadfast_order(
    db: DbSession,
    staff: RequireOrdersWrite,
    order_id: uuid.UUID,
    payload: BookOrderRequest | None = Body(default=None),
) -> CourierShipmentRead:
    return await steadfast_service.book_order(
        db,
        order_id,
        payload or BookOrderRequest(),
        actor=staff,
    )


@router.post("/steadfast/orders/bulk-book", response_model=BulkBookOrdersResponse)
async def bulk_book_steadfast_orders(
    db: DbSession,
    staff: RequireOrdersWrite,
    payload: BulkBookOrdersRequest,
) -> BulkBookOrdersResponse:
    return await steadfast_service.bulk_book_orders(db, payload, actor=staff)


@router.post(
    "/steadfast/orders/{order_id}/refresh-status",
    response_model=RefreshStatusResponse,
)
async def refresh_steadfast_order_status(
    db: DbSession,
    staff: RequireOrdersWrite,
    order_id: uuid.UUID,
) -> RefreshStatusResponse:
    return await steadfast_service.refresh_order_status(db, order_id, actor=staff)


@router.get(
    "/steadfast/orders/{order_id}/tracking",
    response_model=OrderTrackingResponse,
)
async def get_steadfast_order_tracking(
    db: DbSession,
    _staff: RequireOrdersRead,
    order_id: uuid.UUID,
) -> OrderTrackingResponse:
    return await steadfast_service.get_order_tracking(db, order_id)


@router.post("/steadfast/pickup-request", response_model=PickupRequestResponse)
async def create_steadfast_pickup_request(
    _staff: RequireOrdersWrite,
    payload: PickupRequestCreate | None = Body(default=None),
) -> PickupRequestResponse:
    return await steadfast_service.create_pickup_request(payload or PickupRequestCreate())


@router.post("/steadfast/return-requests", response_model=ReturnRequestResponse)
async def create_steadfast_return_request(
    db: DbSession,
    staff: RequireOrdersWrite,
    payload: ReturnRequestCreate,
) -> ReturnRequestResponse:
    return await steadfast_service.create_return_request(db, payload, actor=staff)


@router.get("/steadfast/return-requests")
async def list_steadfast_return_requests(
    _staff: RequireOrdersRead,
) -> list[dict[str, Any]]:
    return await steadfast_service.list_return_requests()


@router.get("/steadfast/return-requests/{request_id}")
async def get_steadfast_return_request(
    _staff: RequireOrdersRead,
    request_id: str,
) -> dict[str, Any]:
    return await steadfast_service.get_return_request(request_id)


@router.get("/steadfast/overview", response_model=SteadfastOverviewResponse)
async def get_steadfast_overview(
    _staff: RequireOrdersRead,
    start_date: str | None = Query(default=None, max_length=32),
    end_date: str | None = Query(default=None, max_length=32),
) -> SteadfastOverviewResponse:
    return await steadfast_service.get_overview(start_date=start_date, end_date=end_date)


@router.post("/steadfast/sync-locations", response_model=SyncLocationsResponse)
async def sync_steadfast_locations(
    db: DbSession,
    _staff: RequireOrdersWrite,
) -> SyncLocationsResponse:
    return await steadfast_service.sync_locations(db)


# ---------------------------------------------------------------------------
# Phase 24 — Superadmin-Only Finance & COD Reconciliation
# ---------------------------------------------------------------------------


@router.get("/steadfast/balance", response_model=SteadfastBalanceResponse)
async def get_steadfast_balance(
    _admin: RequireSuperadmin,
) -> SteadfastBalanceResponse:
    return await steadfast_finance_service.get_balance()


@router.get("/steadfast/payments", response_model=SteadfastPaymentsListResponse)
async def list_steadfast_payments(
    _admin: RequireSuperadmin,
    page: int = Query(default=1, ge=1, le=500),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SteadfastPaymentsListResponse:
    return await steadfast_finance_service.list_payments(page=page, page_size=page_size)


@router.get("/steadfast/payments/{payment_id}", response_model=SteadfastPaymentDetailResponse)
async def get_steadfast_payment_detail(
    db: DbSession,
    _admin: RequireSuperadmin,
    payment_id: str,
) -> SteadfastPaymentDetailResponse:
    return await steadfast_finance_service.get_payment_detail(db, payment_id)


@router.post(
    "/steadfast/payments/{payment_id}/reconcile",
    response_model=SteadfastReconcileResponse,
)
async def reconcile_steadfast_payment(
    db: DbSession,
    admin: RequireSuperadmin,
    payment_id: str,
) -> SteadfastReconcileResponse:
    return await steadfast_finance_service.reconcile_payment(db, payment_id, actor=admin)
