"""Steadfast Courier Operations service (Phase 23).

Orchestrates parcel booking, bulk booking, status/tracking refresh with 60s cooldown,
pickup/return requests, overview stats, and location syncing with strict duplicate
booking protection and order activity logging.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.core.logging import get_logger
from app.models.courier import CourierLocation, CourierShipment
from app.models.order import ActivityAction, Order, OrderStatus
from app.models.user import User
from app.schemas.courier import (
    BookOrderRequest,
    BulkBookOrderItemResult,
    BulkBookOrdersRequest,
    BulkBookOrdersResponse,
    CourierShipmentRead,
    DeliveryDistrictLocations,
    DeliveryLocationsResponse,
    OrderTrackingResponse,
    PickupRequestCreate,
    PickupRequestResponse,
    RefreshStatusResponse,
    ReturnRequestCreate,
    ReturnRequestResponse,
    SteadfastOverviewResponse,
    SteadfastPingResponse,
    SyncLocationsResponse,
)
from app.services import order_service
from app.services.courier.steadfast_client import (
    SteadfastClient,
    SteadfastError,
    steadfast_client,
)
from app.services.redis_client import redis_client

logger = get_logger(__name__)

_PROVIDER = "steadfast"
_INACTIVE_SHIPMENT_STATUSES = frozenset({"cancelled", "cancelled_approval_pending"})
_FINAL_DELIVERED_STATUSES = frozenset({"delivered", "partial_delivered"})
_FINAL_RETURNED_STATUSES = frozenset({"cancelled", "returned"})
_REFRESH_COOLDOWN_PREFIX = "sf:refresh_cd:"
_REFRESH_COOLDOWN_SECONDS = 60
_LOCATIONS_CACHE_KEY = "sf:public:locations:v1"
_LOCATIONS_CACHE_SECONDS = 600


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _order_cod_amount(order: Order) -> int:
    if order.due_amount is not None:
        return max(int(order.due_amount), 0)
    paid = int(order.paid_amount or 0)
    return max(int(order.total) - paid, 0)


def _format_recipient_address(order: Order) -> str:
    parts = [p.strip() for p in (order.address, order.area, order.district) if p and p.strip()]
    return ", ".join(parts)


def _extract_consignment_dict(raw: dict[str, Any]) -> dict[str, Any]:
    nested = raw.get("consignment")
    if isinstance(nested, dict):
        return nested
    data = raw.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("consignment"), dict):
            return data["consignment"]
        return data
    return raw


def _str_or_none(val: Any) -> str | None:
    if val is None:
        return None
    text = str(val).strip()
    return text if text else None


async def ping_steadfast(*, client: SteadfastClient = steadfast_client) -> SteadfastPingResponse:
    data = await client.ping()
    return SteadfastPingResponse(**data)


async def book_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    payload: BookOrderRequest,
    *,
    actor: User,
    client: SteadfastClient = steadfast_client,
) -> CourierShipmentRead:
    order = await db.get(Order, order_id)
    if order is None:
        raise NotFoundError("Order not found")

    if order.status in {OrderStatus.CANCELLED.value, OrderStatus.RETURNED.value}:
        raise ConflictError(f"Cannot book courier for a {order.status} order")

    existing = await db.scalar(
        select(CourierShipment)
        .where(
            CourierShipment.order_id == order.id,
            CourierShipment.provider == _PROVIDER,
            CourierShipment.delivery_status.notin_(_INACTIVE_SHIPMENT_STATUSES),
        )
        .limit(1)
    )
    if existing is not None:
        raise ConflictError(
            f"Order {order.number} already has an active Steadfast shipment "
            f"(consignment_id={existing.consignment_id or existing.tracking_code})"
        )

    cod_amount = (
        payload.cod_amount_override
        if payload.cod_amount_override is not None
        else _order_cod_amount(order)
    )
    sf_payload: dict[str, Any] = {
        "invoice": order.number,
        "recipient_name": payload.recipient_name or order.customer_name,
        "recipient_phone": payload.recipient_phone or order.phone,
        "recipient_address": payload.recipient_address or _format_recipient_address(order),
        "cod_amount": cod_amount,
        "note": payload.note if payload.note is not None else order.notes,
        "delivery_type": payload.delivery_type,
    }

    raw = await client.create_order(sf_payload)
    cons = _extract_consignment_dict(raw)
    consignment_id = _str_or_none(cons.get("consignment_id"))
    tracking_code = _str_or_none(cons.get("tracking_code")) or ""
    delivery_status = _str_or_none(cons.get("status")) or "in_review"
    now = _now_utc()

    shipment = CourierShipment(
        order_id=order.id,
        provider=_PROVIDER,
        invoice=order.number,
        consignment_id=consignment_id,
        tracking_code=tracking_code,
        cod_amount=cod_amount,
        delivery_status=delivery_status,
        booked_by_id=actor.id,
        booked_at=now,
        last_synced_at=now,
        raw_payload=raw,
    )
    db.add(shipment)

    order.courier_name = "Steadfast"
    if tracking_code:
        order.tracking_number = tracking_code

    order_service.log_activity(
        db,
        order.id,
        actor.id,
        ActivityAction.COURIER_BOOKED,
        f"Booked with Steadfast ({tracking_code or consignment_id or order.number})",
        {
            "provider": _PROVIDER,
            "consignment_id": consignment_id,
            "tracking_code": tracking_code,
            "cod_amount": cod_amount,
            "delivery_status": delivery_status,
        },
    )

    await db.commit()
    await db.refresh(shipment)
    return CourierShipmentRead.model_validate(shipment)


async def bulk_book_orders(
    db: AsyncSession,
    payload: BulkBookOrdersRequest,
    *,
    actor: User,
    client: SteadfastClient = steadfast_client,
) -> BulkBookOrdersResponse:
    # Deduplicate preserving order
    unique_ids = list(dict.fromkeys(payload.order_ids))

    # Batch-load orders and active shipments (zero N+1)
    orders_rows = (await db.scalars(select(Order).where(Order.id.in_(unique_ids)))).all()
    orders_by_id = {o.id: o for o in orders_rows}

    active_shipments = (
        await db.scalars(
            select(CourierShipment).where(
                CourierShipment.order_id.in_(unique_ids),
                CourierShipment.provider == _PROVIDER,
                CourierShipment.delivery_status.notin_(_INACTIVE_SHIPMENT_STATUSES),
            )
        )
    ).all()
    booked_order_ids = {s.order_id for s in active_shipments if s.order_id is not None}

    results_by_id: dict[uuid.UUID, BulkBookOrderItemResult] = {}
    eligible_orders: list[Order] = []
    eligible_by_invoice: dict[str, Order] = {}
    outbound: list[dict[str, Any]] = []

    for oid in unique_ids:
        order = orders_by_id.get(oid)
        if order is None:
            results_by_id[oid] = BulkBookOrderItemResult(
                order_id=oid,
                status="skipped",
                message="Order not found",
            )
            continue
        if order.status in {OrderStatus.CANCELLED.value, OrderStatus.RETURNED.value}:
            results_by_id[oid] = BulkBookOrderItemResult(
                order_id=oid,
                order_number=order.number,
                status="skipped",
                message=f"Cannot book a {order.status} order",
            )
            continue
        if oid in booked_order_ids:
            results_by_id[oid] = BulkBookOrderItemResult(
                order_id=oid,
                order_number=order.number,
                status="skipped",
                message="Order already has an active Steadfast shipment",
            )
            continue
        eligible_orders.append(order)
        eligible_by_invoice[order.number] = order
        outbound.append(
            {
                "invoice": order.number,
                "recipient_name": order.customer_name,
                "recipient_phone": order.phone,
                "recipient_address": _format_recipient_address(order),
                "cod_amount": _order_cod_amount(order),
                "note": payload.note if payload.note is not None else order.notes,
            }
        )

    now = _now_utc()
    created_shipments: list[tuple[uuid.UUID, Order, CourierShipment]] = []

    if outbound:
        api_items = await client.bulk_create_orders_extended(outbound)
        matched_invoices: set[str] = set()

        for idx, item in enumerate(api_items):
            inv = _str_or_none(item.get("invoice"))
            order = (
                eligible_by_invoice.get(inv)
                if inv
                else (eligible_orders[idx] if idx < len(eligible_orders) else None)
            )
            if order is None:
                continue
            matched_invoices.add(order.number)

            item_status = str(item.get("status") or "").lower()
            item_errors = item.get("errors")
            has_error = item_status in {"error", "failed", "400", "422"} or (
                isinstance(item_errors, dict) and bool(item_errors)
            ) or (isinstance(item_errors, list) and bool(item_errors))

            consignment_id = _str_or_none(item.get("consignment_id"))
            tracking_code = _str_or_none(item.get("tracking_code")) or ""

            if has_error or (not consignment_id and not tracking_code):
                err_dict: dict[str, Any] = {}
                if isinstance(item_errors, dict):
                    err_dict = item_errors
                elif isinstance(item_errors, list):
                    err_dict = {"errors": item_errors}
                msg = _str_or_none(item.get("message")) or "Steadfast rejected parcel"
                results_by_id[order.id] = BulkBookOrderItemResult(
                    order_id=order.id,
                    order_number=order.number,
                    status="error",
                    errors=err_dict,
                    message=msg,
                )
                continue

            cod = _order_cod_amount(order)
            delivery_status = _str_or_none(item.get("delivery_status")) or "in_review"
            shipment = CourierShipment(
                order_id=order.id,
                provider=_PROVIDER,
                invoice=order.number,
                consignment_id=consignment_id,
                tracking_code=tracking_code,
                cod_amount=cod,
                delivery_status=delivery_status,
                booked_by_id=actor.id,
                booked_at=now,
                last_synced_at=now,
                raw_payload=item,
            )
            db.add(shipment)
            order.courier_name = "Steadfast"
            if tracking_code:
                order.tracking_number = tracking_code
            order_service.log_activity(
                db,
                order.id,
                actor.id,
                ActivityAction.COURIER_BOOKED,
                f"Bulk booked with Steadfast ({tracking_code or consignment_id or order.number})",
                {
                    "provider": _PROVIDER,
                    "consignment_id": consignment_id,
                    "tracking_code": tracking_code,
                    "cod_amount": cod,
                    "delivery_status": delivery_status,
                },
            )
            created_shipments.append((order.id, order, shipment))

        # Any eligible order missing from response is marked error
        for order in eligible_orders:
            if order.number not in matched_invoices:
                results_by_id[order.id] = BulkBookOrderItemResult(
                    order_id=order.id,
                    order_number=order.number,
                    status="error",
                    message="No result returned by Steadfast for this order",
                )

    if created_shipments:
        await db.commit()
        for oid, order, shipment in created_shipments:
            await db.refresh(shipment)
            results_by_id[oid] = BulkBookOrderItemResult(
                order_id=oid,
                order_number=order.number,
                status="booked",
                shipment=CourierShipmentRead.model_validate(shipment),
                message="Booked successfully",
            )

    ordered_results = [results_by_id[oid] for oid in unique_ids]
    return BulkBookOrdersResponse(
        requested=len(unique_ids),
        booked=sum(1 for r in ordered_results if r.status == "booked"),
        skipped=sum(1 for r in ordered_results if r.status == "skipped"),
        failed=sum(1 for r in ordered_results if r.status == "error"),
        results=ordered_results,
    )


async def _latest_shipment_or_404(db: AsyncSession, order_id: uuid.UUID) -> CourierShipment:
    shipment = await db.scalar(
        select(CourierShipment)
        .where(CourierShipment.order_id == order_id, CourierShipment.provider == _PROVIDER)
        .order_by(CourierShipment.created_at.desc(), CourierShipment.id.desc())
        .limit(1)
    )
    if shipment is None:
        raise NotFoundError("No Steadfast shipment found for this order")
    return shipment


async def _apply_final_status_sync(
    db: AsyncSession,
    order: Order,
    shipment: CourierShipment,
    *,
    actor_id: uuid.UUID | None,
) -> None:
    ds = (shipment.delivery_status or "").lower()
    rs = (shipment.return_status or "").lower()

    # NEVER finalize order status or accounting on unconfirmed *_approval_pending rider claims.
    if ds.endswith("_approval_pending") or rs.endswith("_approval_pending"):
        shipment.is_final = False
        return

    if ds == "delivered":
        shipment.is_final = True
        if order.status == OrderStatus.SHIPPED.value:
            await order_service.change_status(
                db, order, OrderStatus.DELIVERED.value, actor_id=actor_id
            )
    elif ds == "partial_delivered":
        # Staff must review partial items/amount before updating order totals.
        shipment.is_final = True
        if rs == "partial_delivered_return_received":
            shipment.is_return_received = True
    elif ds == "cancelled":
        shipment.is_final = True
        if rs == "cancelled_return_received":
            shipment.is_return_received = True


async def refresh_order_status(
    db: AsyncSession,
    order_id: uuid.UUID,
    *,
    actor: User,
    client: SteadfastClient = steadfast_client,
) -> RefreshStatusResponse:
    order = await db.get(Order, order_id)
    if order is None:
        raise NotFoundError("Order not found")

    shipment = await _latest_shipment_or_404(db, order_id)
    cd_key = f"{_REFRESH_COOLDOWN_PREFIX}{shipment.id}"
    if await redis_client.get_str(cd_key) is not None:
        return RefreshStatusResponse(
            shipment=CourierShipmentRead.model_validate(shipment),
            order_status=order.status,
            cooldown_cached=True,
            tracking_events=list(shipment.tracking_events or []),
        )

    if not shipment.consignment_id:
        raise UnprocessableError("Shipment has no Steadfast consignment_id to refresh")

    status_body = await client.status_with_return_by_cid(shipment.consignment_id, use_cache=False)
    events, _ = await client.trackings_by_invoice(shipment.invoice, use_cache=False)

    new_delivery_status = (
        _str_or_none(status_body.get("delivery_status"))
        or _str_or_none(status_body.get("status"))
        or shipment.delivery_status
    )
    new_return_status = _str_or_none(status_body.get("return_status")) or shipment.return_status

    shipment.delivery_status = new_delivery_status
    shipment.return_status = new_return_status
    if events:
        shipment.tracking_events = events
    shipment.last_synced_at = _now_utc()
    shipment.raw_payload = {**(shipment.raw_payload or {}), "last_status": status_body}

    await _apply_final_status_sync(db, order, shipment, actor_id=actor.id)
    await db.commit()
    await db.refresh(shipment)
    await db.refresh(order)

    await redis_client.set_str(cd_key, "1", ttl_seconds=_REFRESH_COOLDOWN_SECONDS)

    return RefreshStatusResponse(
        shipment=CourierShipmentRead.model_validate(shipment),
        order_status=order.status,
        cooldown_cached=False,
        tracking_events=list(shipment.tracking_events or []),
    )


async def get_order_tracking(
    db: AsyncSession,
    order_id: uuid.UUID,
    *,
    client: SteadfastClient = steadfast_client,
) -> OrderTrackingResponse:
    shipment = await _latest_shipment_or_404(db, order_id)
    cached = True
    events = list(shipment.tracking_events or [])
    if client.configured():
        try:
            live_events, from_cache = await client.trackings_by_invoice(
                shipment.invoice, use_cache=True
            )
            cached = from_cache
            if live_events:
                events = live_events
                if not from_cache:
                    shipment.tracking_events = live_events
                    shipment.last_synced_at = _now_utc()
                    await db.commit()
                    await db.refresh(shipment)
        except SteadfastError:
            # Return stored tracking events gracefully if Steadfast is unreachable.
            cached = True
    return OrderTrackingResponse(
        shipment=CourierShipmentRead.model_validate(shipment),
        tracking_events=events,
        cached=cached,
    )


async def create_pickup_request(
    payload: PickupRequestCreate,
    *,
    client: SteadfastClient = steadfast_client,
) -> PickupRequestResponse:
    address = (payload.address or settings.steadfast_pickup_address or "").strip()
    if not address:
        raise UnprocessableError(
            "Pickup address is required (pass address or configure STEADFAST_PICKUP_ADDRESS)"
        )
    phone = (payload.phone or settings.steadfast_pickup_phone or "").strip()
    raw = await client.create_pickup_request(address=address, phone=phone, note=payload.note)
    return PickupRequestResponse(ok=True, raw=raw)


async def create_return_request(
    db: AsyncSession,
    payload: ReturnRequestCreate,
    *,
    actor: User,
    client: SteadfastClient = steadfast_client,
) -> ReturnRequestResponse:
    consignment_id = payload.consignment_id
    invoice = payload.invoice
    tracking_code = payload.tracking_code
    linked_order_id = payload.order_id

    if linked_order_id is not None:
        shipment = await _latest_shipment_or_404(db, linked_order_id)
        consignment_id = consignment_id or shipment.consignment_id
        invoice = invoice or shipment.invoice
        tracking_code = tracking_code or shipment.tracking_code

    if not any((consignment_id, invoice, tracking_code)):
        raise UnprocessableError(
            "Provide order_id, consignment_id, invoice, or tracking_code for return request"
        )

    raw = await client.create_return_request(
        consignment_id=consignment_id,
        invoice=invoice,
        tracking_code=tracking_code,
        reason=payload.reason,
    )

    if linked_order_id is not None:
        order_service.log_activity(
            db,
            linked_order_id,
            actor.id,
            ActivityAction.RETURN_REQUESTED,
            f"Steadfast return requested ({consignment_id or invoice})",
            {
                "provider": _PROVIDER,
                "consignment_id": consignment_id,
                "invoice": invoice,
                "reason": payload.reason,
            },
        )
        await db.commit()

    return ReturnRequestResponse(ok=True, data=raw)


async def list_return_requests(
    *, client: SteadfastClient = steadfast_client
) -> list[dict[str, Any]]:
    return await client.list_return_requests()


async def get_return_request(
    request_id: str, *, client: SteadfastClient = steadfast_client
) -> dict[str, Any]:
    return await client.get_return_request(request_id)


async def get_overview(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    client: SteadfastClient = steadfast_client,
) -> SteadfastOverviewResponse:
    parcel_states, cached = await client.get_parcel_states(use_cache=True)
    balance_body = await client.get_balance()
    balance_raw = balance_body.get("current_balance")
    balance = float(balance_raw) if isinstance(balance_raw, (int, float)) else None
    stats = (
        await client.get_stats(start_date=start_date, end_date=end_date)
        if (start_date or end_date)
        else None
    )
    return SteadfastOverviewResponse(
        balance=balance,
        parcel_states=parcel_states,
        stats=stats,
        cached=cached,
    )


async def sync_locations(
    db: AsyncSession,
    *,
    client: SteadfastClient = steadfast_client,
) -> SyncLocationsResponse:
    raw_rows = await client.get_police_stations()
    pairs: set[tuple[str, str]] = set()
    for row in raw_rows:
        district = _str_or_none(
            row.get("district") or row.get("district_name") or row.get("city")
        )
        ps = _str_or_none(
            row.get("police_station")
            or row.get("police_station_name")
            or row.get("thana")
            or row.get("name")
            or row.get("area")
        )
        if district and ps:
            pairs.add((district[:120], ps[:160]))

    existing_rows = (
        await db.scalars(select(CourierLocation).where(CourierLocation.provider == _PROVIDER))
    ).all()
    existing_map = {(r.district, r.police_station): r for r in existing_rows}

    now = _now_utc()
    for district, ps in pairs:
        existing = existing_map.get((district, ps))
        if existing is not None:
            existing.synced_at = now
        else:
            db.add(
                CourierLocation(
                    provider=_PROVIDER,
                    district=district,
                    police_station=ps,
                    synced_at=now,
                )
            )

    await db.commit()
    await redis_client.delete_key(_LOCATIONS_CACHE_KEY)

    districts = {d for d, _ in pairs}
    return SyncLocationsResponse(
        provider=_PROVIDER,
        synced_count=len(pairs),
        districts_count=len(districts),
        synced_at=now,
    )


async def get_public_delivery_locations(db: AsyncSession) -> DeliveryLocationsResponse:
    cached = await redis_client.get_json(_LOCATIONS_CACHE_KEY)
    if isinstance(cached, dict) and isinstance(cached.get("districts"), list):
        return DeliveryLocationsResponse.model_validate(cached)

    rows = (
        await db.scalars(
            select(CourierLocation)
            .where(CourierLocation.provider == _PROVIDER)
            .order_by(CourierLocation.district.asc(), CourierLocation.police_station.asc())
        )
    ).all()

    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(row.district, []).append(row.police_station)

    districts = [
        DeliveryDistrictLocations(name=district, areas=areas)
        for district, areas in sorted(grouped.items())
    ]
    response = DeliveryLocationsResponse(
        provider=_PROVIDER,
        districts=districts,
        total_areas=len(rows),
    )
    await redis_client.set_json(
        _LOCATIONS_CACHE_KEY,
        response.model_dump(),
        ttl_seconds=_LOCATIONS_CACHE_SECONDS,
    )
    return response
