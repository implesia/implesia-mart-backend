"""Steadfast webhook receiver business logic (Phase 24).

Enforces strict accounting & operational safety rules:
- Constant-time auth against ``STEADFAST_WEBHOOK_SECRET`` (fail closed when empty).
- Idempotent recording in ``courier_webhook_events`` via deterministic ``event_key``.
- NEVER finalizes Order status, stock, or profit reports on ``*_approval_pending``.
- Auto-transitions confirmed ``delivered`` orders (stepping cleanly through allowed
  order transitions so ``delivered_at``, customer notifications, WebSocket push, and
  Web Push all trigger automatically).
- Flags ``partial_delivered`` for staff review without overwriting order totals.
- Tracks ``cancelled`` return progression and sets ``is_return_received = True`` ONLY
  when ``cancelled_return_received`` or ``partial_delivered_return_received`` arrives.
- Logs alerts and schedules optional Telegram notifications for ``hold`` / ``exceptional``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.logging import get_logger
from app.models.courier import CourierShipment, CourierWebhookEvent
from app.models.order import ActivityAction, Order, OrderStatus
from app.schemas.courier import SteadfastWebhookResponse
from app.services import notification_service, order_service, telegram_notify
from app.services.realtime_hub import STAFF_ORDERS_CHANNEL, realtime_hub

logger = get_logger(__name__)

_PROVIDER = "steadfast"

_APPROVAL_PENDING_STATUSES = frozenset(
    {
        "delivered_approval_pending",
        "partial_delivered_approval_pending",
        "cancelled_approval_pending",
        "unknown_approval_pending",
    }
)

_RETURN_RECEIVED_STATUSES = frozenset(
    {
        "cancelled_return_received",
        "partial_delivered_return_received",
    }
)

_CANCELLED_RETURN_PROGRESS = frozenset(
    {
        "cancelled_return_proccessing",
        "cancelled_return_processing",
        "cancelled_return_rider_assigned",
        "cancelled_return_received",
    }
)

_PARTIAL_RETURN_PROGRESS = frozenset(
    {
        "partial_delivered_return_proccessing",
        "partial_delivered_return_processing",
        "partial_delivered_return_rider_assigned",
        "partial_delivered_return_received",
    }
)

_ALERT_STATUSES = frozenset({"hold", "exceptional"})

# Ordered forward steps used to advance confirmed/packed/shipped -> delivered
_DELIVER_CHAIN: dict[str, tuple[str, ...]] = {
    OrderStatus.CONFIRMED.value: (
        OrderStatus.PACKED.value,
        OrderStatus.SHIPPED.value,
        OrderStatus.DELIVERED.value,
    ),
    OrderStatus.PACKED.value: (
        OrderStatus.SHIPPED.value,
        OrderStatus.DELIVERED.value,
    ),
    OrderStatus.SHIPPED.value: (OrderStatus.DELIVERED.value,),
}


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _str_or_none(val: Any) -> str | None:
    if val is None:
        return None
    text = str(val).strip()
    return text if text else None


def verify_webhook_secret(
    *,
    authorization: str | None = None,
    header_tokens: tuple[str | None, ...] = (),
) -> None:
    """Authenticate Steadfast webhook using constant-time comparison.

    Fails closed whenever ``STEADFAST_WEBHOOK_SECRET`` is empty (especially in production).
    Accepts ``Authorization: Bearer <secret>`` or a dedicated secret header.
    """
    expected = settings.steadfast_webhook_secret.get_secret_value().strip()
    if not expected:
        logger.warning(
            "steadfast_webhook_rejected_unconfigured",
            environment=settings.environment,
        )
        raise AuthenticationError("Steadfast webhook secret is not configured")

    candidates: list[str] = []
    if authorization:
        auth_clean = authorization.strip()
        if auth_clean.lower().startswith("bearer "):
            candidates.append(auth_clean[7:].strip())
        else:
            candidates.append(auth_clean)
    for token in header_tokens:
        if token and token.strip():
            candidates.append(token.strip())

    for provided in candidates:
        if hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8")):
            return

    raise AuthenticationError("Invalid Steadfast webhook credentials")


def build_event_key(payload: dict[str, Any]) -> str:
    """Build a deterministic idempotency key (<= 200 chars) for a webhook payload."""
    for explicit_key in ("event_id", "webhook_id", "notification_id"):
        raw = _str_or_none(payload.get(explicit_key))
        if raw:
            return f"steadfast:{raw[:180]}"

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"steadfast:{digest}"


def _is_approval_pending(status_value: str) -> bool:
    return status_value in _APPROVAL_PENDING_STATUSES or status_value.endswith("_approval_pending")


async def _find_shipment_and_order(
    db: AsyncSession,
    *,
    consignment_id: str | None,
    invoice: str | None,
) -> tuple[CourierShipment | None, Order | None]:
    shipment: CourierShipment | None = None
    if consignment_id:
        shipment = await db.scalar(
            select(CourierShipment)
            .where(
                CourierShipment.provider == _PROVIDER,
                CourierShipment.consignment_id == consignment_id,
            )
            .limit(1)
        )
    if shipment is None and invoice:
        shipment = await db.scalar(
            select(CourierShipment)
            .where(
                CourierShipment.provider == _PROVIDER,
                CourierShipment.invoice == invoice,
            )
            .order_by(CourierShipment.created_at.desc(), CourierShipment.id.desc())
            .limit(1)
        )

    order: Order | None = None
    if shipment is not None and shipment.order_id is not None:
        order = (
            await db.execute(
                select(Order)
                .options(selectinload(Order.items))
                .where(Order.id == shipment.order_id)
            )
        ).scalar_one_or_none()
    elif invoice:
        order = (
            await db.execute(
                select(Order).options(selectinload(Order.items)).where(Order.number == invoice)
            )
        ).scalar_one_or_none()

    # If the order exists locally (e.g. booked from Steadfast portal directly), create shipment row
    if shipment is None and order is not None:
        cod = int(order.due_amount) if order.due_amount is not None else int(order.total)
        shipment = CourierShipment(
            order_id=order.id,
            provider=_PROVIDER,
            invoice=order.number,
            consignment_id=consignment_id,
            tracking_code=order.tracking_number or "",
            cod_amount=max(cod, 0),
            delivery_status="in_review",
        )
        db.add(shipment)
        await db.flush()

    return shipment, order


async def process_steadfast_webhook(
    db: AsyncSession,
    payload: dict[str, Any],
    *,
    background: BackgroundTasks | None = None,
) -> SteadfastWebhookResponse:
    event_key = build_event_key(payload)
    notification_type = (
        _str_or_none(payload.get("notification_type"))
        or _str_or_none(payload.get("event_type"))
        or _str_or_none(payload.get("type"))
        or "delivery_status"
    ).lower()
    consignment_id = _str_or_none(payload.get("consignment_id"))
    invoice = _str_or_none(payload.get("invoice"))
    raw_status = (
        _str_or_none(payload.get("delivery_status"))
        or _str_or_none(payload.get("status"))
        or ""
    ).lower()
    explicit_return_status = (_str_or_none(payload.get("return_status")) or "").lower() or None
    tracking_message = _str_or_none(payload.get("tracking_message")) or ""
    updated_at_str = _str_or_none(payload.get("updated_at")) or _now_utc().isoformat()

    # 1. Idempotency check & atomic insert
    existing_event = await db.scalar(
        select(CourierWebhookEvent).where(CourierWebhookEvent.event_key == event_key).limit(1)
    )
    if existing_event is not None:
        return SteadfastWebhookResponse(
            ok=True,
            status="duplicate",
            event_key=event_key,
            order_number=invoice,
        )

    webhook_row = CourierWebhookEvent(
        provider=_PROVIDER,
        event_key=event_key,
        consignment_id=consignment_id,
        invoice=invoice,
        event_type=notification_type[:64],
        payload=payload,
        processed_at=_now_utc(),
    )
    try:
        async with db.begin_nested():
            db.add(webhook_row)
            await db.flush()
    except IntegrityError:
        return SteadfastWebhookResponse(
            ok=True,
            status="duplicate",
            event_key=event_key,
            order_number=invoice,
        )

    # 2. Match shipment & order
    shipment, order = await _find_shipment_and_order(
        db,
        consignment_id=consignment_id,
        invoice=invoice,
    )

    if shipment is None:
        await db.commit()
        logger.info(
            "steadfast_webhook_unmatched",
            event_key=event_key,
            consignment_id=consignment_id,
            invoice=invoice,
        )
        return SteadfastWebhookResponse(
            ok=True,
            status="ignored",
            event_key=event_key,
            order_number=invoice,
            delivery_status=raw_status or None,
            return_status=explicit_return_status,
        )

    now = _now_utc()
    shipment.last_synced_at = now
    shipment.raw_payload = {**(shipment.raw_payload or {}), "last_webhook": payload}

    # Append tracking event if tracking_message or status update present
    existing_events = list(shipment.tracking_events or [])
    if tracking_message or raw_status:
        existing_events.append(
            {
                "status": raw_status or shipment.delivery_status,
                "message": tracking_message,
                "timestamp": updated_at_str,
                "source": "webhook",
                "notification_type": notification_type,
            }
        )
        shipment.tracking_events = existing_events

    if explicit_return_status:
        shipment.return_status = explicit_return_status

    # Track actions to fire AFTER db.commit()
    auto_delivered_order_id: Any = None
    staff_alert_kind: str | None = None
    send_telegram_alert = False

    # 3. Apply critical accounting & status rules
    if raw_status:
        if _is_approval_pending(raw_status):
            # CRITICAL: NEVER finalize Order status, stock, or profit reports on *_approval_pending
            shipment.delivery_status = raw_status
            shipment.is_final = False
            if order is not None:
                order_service.log_activity(
                    db,
                    order.id,
                    None,
                    ActivityAction.COURIER_WEBHOOK,
                    f"Steadfast unconfirmed update: {raw_status} (awaiting Steadfast approval)",
                    {
                        "provider": _PROVIDER,
                        "consignment_id": consignment_id,
                        "delivery_status": raw_status,
                        "approval_pending": True,
                        "tracking_message": tracking_message,
                    },
                )

        elif raw_status == "delivered":
            shipment.delivery_status = "delivered"
            shipment.is_final = True
            if order is not None:
                order_service.log_activity(
                    db,
                    order.id,
                    None,
                    ActivityAction.COURIER_WEBHOOK,
                    "Steadfast confirmed delivery",
                    {
                        "provider": _PROVIDER,
                        "consignment_id": consignment_id,
                        "delivery_status": "delivered",
                        "tracking_message": tracking_message,
                    },
                )
                steps = _DELIVER_CHAIN.get(order.status)
                if steps:
                    for step_status in steps:
                        await order_service.change_status(db, order, step_status, actor_id=None)
                        await db.refresh(order)
                    auto_delivered_order_id = order.id

        elif raw_status == "partial_delivered":
            # CRITICAL: Do NOT overwrite order total or auto-complete; require staff review
            shipment.delivery_status = "partial_delivered"
            shipment.is_final = True
            staff_alert_kind = "partial_delivered"
            send_telegram_alert = True
            if order is not None:
                order_service.log_activity(
                    db,
                    order.id,
                    None,
                    ActivityAction.COURIER_WEBHOOK,
                    "URGENT: Steadfast confirmed partial delivery — staff review required",
                    {
                        "provider": _PROVIDER,
                        "priority": "high",
                        "requires_staff_review": True,
                        "consignment_id": consignment_id,
                        "delivery_status": "partial_delivered",
                        "cod_amount": payload.get("cod_amount"),
                        "tracking_message": tracking_message,
                    },
                )

        elif raw_status == "cancelled":
            shipment.delivery_status = "cancelled"
            shipment.is_final = True
            # Only mark return received if return_status explicitly confirms physical receipt
            if explicit_return_status in _RETURN_RECEIVED_STATUSES:
                shipment.is_return_received = True
            if order is not None:
                order_service.log_activity(
                    db,
                    order.id,
                    None,
                    ActivityAction.COURIER_WEBHOOK,
                    "Steadfast confirmed parcel cancellation (awaiting physical return receipt)",
                    {
                        "provider": _PROVIDER,
                        "consignment_id": consignment_id,
                        "delivery_status": "cancelled",
                        "return_status": shipment.return_status,
                        "is_return_received": shipment.is_return_received,
                        "tracking_message": tracking_message,
                    },
                )

        elif raw_status in _CANCELLED_RETURN_PROGRESS or raw_status in _PARTIAL_RETURN_PROGRESS:
            shipment.return_status = raw_status
            if raw_status in _CANCELLED_RETURN_PROGRESS:
                shipment.delivery_status = "cancelled"
                shipment.is_final = True
            elif raw_status in _PARTIAL_RETURN_PROGRESS:
                shipment.delivery_status = "partial_delivered"
                shipment.is_final = True

            if raw_status in _RETURN_RECEIVED_STATUSES:
                shipment.is_return_received = True

            if order is not None:
                summary = (
                    f"Steadfast physical return received ({raw_status}) — ready for restock"
                    if shipment.is_return_received
                    else f"Steadfast return progression: {raw_status}"
                )
                order_service.log_activity(
                    db,
                    order.id,
                    None,
                    ActivityAction.COURIER_WEBHOOK,
                    summary,
                    {
                        "provider": _PROVIDER,
                        "consignment_id": consignment_id,
                        "delivery_status": shipment.delivery_status,
                        "return_status": raw_status,
                        "is_return_received": shipment.is_return_received,
                        "tracking_message": tracking_message,
                    },
                )

        elif raw_status in _ALERT_STATUSES:
            shipment.delivery_status = raw_status
            staff_alert_kind = raw_status
            send_telegram_alert = True
            if order is not None:
                order_service.log_activity(
                    db,
                    order.id,
                    None,
                    ActivityAction.COURIER_WEBHOOK,
                    f"Steadfast courier alert: {raw_status}",
                    {
                        "provider": _PROVIDER,
                        "alert": True,
                        "priority": "high",
                        "consignment_id": consignment_id,
                        "delivery_status": raw_status,
                        "tracking_message": tracking_message,
                    },
                )

        else:
            shipment.delivery_status = raw_status
            if explicit_return_status in _RETURN_RECEIVED_STATUSES:
                shipment.is_return_received = True
            if order is not None:
                order_service.log_activity(
                    db,
                    order.id,
                    None,
                    ActivityAction.COURIER_WEBHOOK,
                    f"Steadfast update: {raw_status}",
                    {
                        "provider": _PROVIDER,
                        "consignment_id": consignment_id,
                        "delivery_status": raw_status,
                        "return_status": shipment.return_status,
                        "tracking_message": tracking_message,
                    },
                )
    else:
        # Pure tracking_update webhook without status change
        if explicit_return_status in _RETURN_RECEIVED_STATUSES:
            shipment.is_return_received = True
        if order is not None:
            order_service.log_activity(
                db,
                order.id,
                None,
                ActivityAction.COURIER_WEBHOOK,
                f"Steadfast tracking update: {tracking_message[:140]}"
                if tracking_message
                else "Steadfast tracking update",
                {
                    "provider": _PROVIDER,
                    "consignment_id": consignment_id,
                    "notification_type": notification_type,
                    "tracking_message": tracking_message,
                },
            )

    await db.commit()
    await db.refresh(shipment)
    if order is not None:
        await db.refresh(order)

    # 4. Post-commit side effects (notifications, WS fan-out, optional Telegram alert)
    if auto_delivered_order_id is not None and order is not None:
        await notification_service.create_order_status_notification(
            db,
            order,
            OrderStatus.DELIVERED.value,
        )
        await realtime_hub.publish(
            STAFF_ORDERS_CHANNEL,
            "order.updated",
            {
                "order_id": str(order.id),
                "order_number": order.number,
                "status": order.status,
                "delivery_status": shipment.delivery_status,
                "source": "steadfast_webhook",
            },
        )

    if staff_alert_kind is not None:
        order_num = order.number if order is not None else (invoice or shipment.invoice)
        await realtime_hub.publish(
            STAFF_ORDERS_CHANNEL,
            "courier.alert",
            {
                "order_id": str(order.id) if order is not None else None,
                "order_number": order_num,
                "provider": _PROVIDER,
                "status": staff_alert_kind,
                "consignment_id": consignment_id or shipment.consignment_id,
                "tracking_message": tracking_message,
            },
        )
        if send_telegram_alert:
            telegram_notify.schedule_courier_alert(
                background,
                order_id=order.id if order is not None else None,
                order_number=order_num,
                status=staff_alert_kind,
                consignment_id=consignment_id or shipment.consignment_id,
                tracking_message=tracking_message,
            )

    return SteadfastWebhookResponse(
        ok=True,
        status="processed",
        event_key=event_key,
        order_number=order.number if order is not None else shipment.invoice,
        order_status=order.status if order is not None else None,
        delivery_status=shipment.delivery_status,
        return_status=shipment.return_status,
        is_return_received=shipment.is_return_received,
    )
