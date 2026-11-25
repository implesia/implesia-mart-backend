"""Customer-safe live courier tracking presenter (Phase 24).

Enriches customer tracking & public order lookup with live Steadfast events while
strictly sanitizing internal states:
- NEVER exposes raw ``*_approval_pending`` strings, ``fraud_score``, ``merchant_reports``,
  or internal admin/staff notes to customers or public lookup callers.
- Fetches cached 60-second ``trackings_by_invoice`` on demand when a Steadfast shipment
  is active and not yet final, gracefully falling back to stored events if Steadfast is
  unreachable or unconfigured.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courier import CourierShipment
from app.models.order import Order
from app.services.courier.steadfast_client import (
    SteadfastClient,
    SteadfastError,
    steadfast_client,
)

_PROVIDER = "steadfast"
_SENSITIVE_PATTERN = re.compile(
    r"(?:approval_pending|fraud_score|merchant_reports|internal_note|admin_note|staff_note)",
    re.IGNORECASE,
)

# Map internal Steadfast statuses -> (public_status, customer_friendly_label, default_message)
_STATUS_LABELS: dict[str, tuple[str, str, str]] = {
    "in_review": (
        "in_review",
        "Courier Processing",
        "Parcel received by courier for processing.",
    ),
    "pending": (
        "pending",
        "Booked with Courier",
        "Parcel is scheduled for pickup by courier.",
    ),
    "hold": (
        "on_hold",
        "Temporarily Held at Hub",
        "Parcel is currently held at the courier hub.",
    ),
    "exceptional": (
        "delayed",
        "Delivery Delayed",
        "Courier is reviewing a delivery exception.",
    ),
    "delivered": (
        "delivered",
        "Delivered",
        "Parcel has been delivered successfully.",
    ),
    "partial_delivered": (
        "partial_delivered",
        "Partially Delivered",
        "Parcel was partially delivered.",
    ),
    "cancelled": (
        "cancelled",
        "Delivery Cancelled",
        "Courier delivery was cancelled.",
    ),
    # Unconfirmed rider claims MUST NOT leak *_approval_pending to customers
    "delivered_approval_pending": (
        "in_transit",
        "Delivery Update in Progress",
        "Courier is confirming the delivery update.",
    ),
    "partial_delivered_approval_pending": (
        "in_transit",
        "Delivery Update in Progress",
        "Courier is confirming delivery details.",
    ),
    "cancelled_approval_pending": (
        "in_transit",
        "Delivery Attempt Update",
        "Courier is updating the delivery attempt status.",
    ),
    "unknown_approval_pending": (
        "in_transit",
        "In Transit",
        "Parcel is being processed by courier.",
    ),
    # Return progression
    "cancelled_return_proccessing": (
        "returning",
        "Returning to Merchant",
        "Parcel is being prepared for return.",
    ),
    "cancelled_return_processing": (
        "returning",
        "Returning to Merchant",
        "Parcel is being prepared for return.",
    ),
    "cancelled_return_rider_assigned": (
        "returning",
        "Return in Transit",
        "Parcel is on its way back to merchant.",
    ),
    "cancelled_return_received": (
        "returned",
        "Returned to Merchant",
        "Returned parcel has been received by merchant.",
    ),
    "partial_delivered_return_proccessing": (
        "returning",
        "Partial Return Processing",
        "Remaining item is being processed for return.",
    ),
    "partial_delivered_return_processing": (
        "returning",
        "Partial Return Processing",
        "Remaining item is being processed for return.",
    ),
    "partial_delivered_return_rider_assigned": (
        "returning",
        "Partial Return in Transit",
        "Remaining item is on its way back to merchant.",
    ),
    "partial_delivered_return_received": (
        "returned",
        "Partial Return Received",
        "Returned item has been received by merchant.",
    ),
}


def map_customer_status(raw_status: str | None) -> tuple[str, str, str]:
    key = (raw_status or "").strip().lower()
    if not key:
        return ("in_transit", "Courier Update", "Parcel status updated by courier.")
    if key in _STATUS_LABELS:
        return _STATUS_LABELS[key]
    if key.endswith("_approval_pending") or "approval_pending" in key:
        return (
            "in_transit",
            "Delivery Update in Progress",
            "Courier is confirming the delivery update.",
        )
    if "return" in key:
        return ("returning", "Returning to Merchant", "Parcel is in return transit.")
    return (
        "in_transit",
        "In Transit",
        "Parcel is on the way with courier.",
    )


def _sanitize_message(raw_message: Any, fallback: str) -> str:
    if not isinstance(raw_message, str):
        return fallback
    text = raw_message.strip()
    if not text:
        return fallback
    if _SENSITIVE_PATTERN.search(text):
        return fallback
    return text[:240]


def _extract_timestamp(event: dict[str, Any]) -> str | None:
    for key in ("timestamp", "created_at", "updated_at", "time", "date"):
        val = event.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:64]
    return None


def sanitize_customer_tracking_events(
    raw_events: list[dict[str, Any]],
    shipment: CourierShipment,
) -> list[dict[str, Any]]:
    """Return a strict allowlist of customer-safe tracking events."""
    sanitized: list[dict[str, Any]] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        raw_status = (
            item.get("delivery_status")
            or item.get("status")
            or item.get("state")
            or shipment.delivery_status
        )
        pub_status, label, default_msg = map_customer_status(
            str(raw_status) if raw_status is not None else None
        )
        raw_msg = (
            item.get("message")
            or item.get("tracking_message")
            or item.get("event")
            or item.get("description")
        )
        message = _sanitize_message(raw_msg, default_msg)
        sanitized.append(
            {
                "status": pub_status,
                "label": label,
                "message": message,
                "timestamp": _extract_timestamp(item),
            }
        )

    if not sanitized:
        pub_status, label, default_msg = map_customer_status(
            shipment.return_status or shipment.delivery_status
        )
        ts = shipment.last_synced_at or shipment.booked_at or shipment.created_at
        sanitized.append(
            {
                "status": pub_status,
                "label": label,
                "message": default_msg,
                "timestamp": ts.isoformat() if isinstance(ts, datetime) else None,
            }
        )

    return sanitized


async def get_customer_live_tracking(
    db: AsyncSession,
    order: Order,
    *,
    client: SteadfastClient = steadfast_client,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch & sanitize live Steadfast tracking events and tracking URL for an order."""
    shipment = await db.scalar(
        select(CourierShipment)
        .where(CourierShipment.order_id == order.id, CourierShipment.provider == _PROVIDER)
        .order_by(CourierShipment.created_at.desc(), CourierShipment.id.desc())
        .limit(1)
    )
    if shipment is None:
        return [], None

    raw_events = [e for e in (shipment.tracking_events or []) if isinstance(e, dict)]

    if not shipment.is_final and client.configured():
        try:
            live_events, from_cache = await client.trackings_by_invoice(
                shipment.invoice, use_cache=True
            )
            if live_events:
                raw_events = live_events
                if not from_cache:
                    shipment.tracking_events = live_events
                    shipment.last_synced_at = datetime.now(UTC)
                    await db.commit()
                    await db.refresh(shipment)
        except SteadfastError:
            # Graceful degradation: serve stored events when Steadfast is unavailable
            pass

    tracking_url = (
        f"https://steadfast.com.bd/t/{shipment.tracking_code}"
        if shipment.tracking_code
        else None
    )
    return sanitize_customer_tracking_events(raw_events, shipment), tracking_url
