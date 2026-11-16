"""Meta Conversions API Purchase events.

Sent once, after a new order is committed. A failure here must not change the
order response. The access token and the raw phone or email are never logged:
httpx error text can include the request URL, so failures log the order number
and a status or error kind only.
"""

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from starlette.background import BackgroundTasks

from app.core.config import settings
from app.core.logging import get_logger
from app.models.order import Order, OrderItem
from app.schemas.order import OrderTracking, purchase_event_id

logger = get_logger("meta_capi")

# Graph API version is fixed here. It is not an environment variable.
GRAPH_API_VERSION = "v21.0"
HTTP_TIMEOUT = httpx.Timeout(5.0)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.5, 1.0)

_PHONE_SEPARATORS = re.compile(r"[\s+\-]")
_LOCAL_MOBILE = re.compile(r"01\d{9}")
_INTL_MOBILE = re.compile(r"8801\d{9}")


def enabled() -> bool:
    return settings.meta_capi_enabled


def normalize_phone(phone: str) -> str | None:
    """``8801XXXXXXXXX``, or None when the number cannot be normalised.

    Spaces, dashes and ``+`` are removed. ``01XXXXXXXXX`` gains the ``88``
    country prefix. A number that is already ``8801XXXXXXXXX`` stays as it is.
    """
    compact = _PHONE_SEPARATORS.sub("", phone)
    if _LOCAL_MOBILE.fullmatch(compact):
        compact = "88" + compact
    if _INTL_MOBILE.fullmatch(compact):
        return compact
    return None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_email(email: str) -> str | None:
    cleaned = email.strip().lower()
    if not cleaned:
        return None
    return _sha256(cleaned)


def hash_phone(phone: str) -> str | None:
    normalized = normalize_phone(phone)
    if normalized is None:
        return None
    return _sha256(normalized)


def _event_time(created: datetime | None) -> int:
    if not isinstance(created, datetime):
        return int(datetime.now(UTC).timestamp())
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return int(created.timestamp())


def _lines(items: list[OrderItem]) -> list[OrderItem]:
    return [item for item in items if item.product_id is not None]


def build_purchase_body(order: Order, tracking: OrderTracking | None) -> dict[str, Any]:
    """Graph API body for one Purchase. Hashes only; no name, address, IP or user agent."""
    lines = _lines(list(order.items))
    user_data: dict[str, Any] = {}
    phone_hash = hash_phone(order.phone)
    if phone_hash is not None:
        user_data["ph"] = [phone_hash]
    email_hash = hash_email(order.email or "")
    if email_hash is not None:
        user_data["em"] = [email_hash]
    if tracking is not None and tracking.fbp:
        user_data["fbp"] = tracking.fbp
    if tracking is not None and tracking.fbc:
        user_data["fbc"] = tracking.fbc

    event: dict[str, Any] = {
        "event_name": "Purchase",
        "event_time": _event_time(order.created_at),
        "event_id": purchase_event_id(order.number),
        "action_source": "website",
        "custom_data": {
            "value": int(order.total),
            "currency": "BDT",
            "content_ids": [str(item.product_id) for item in lines],
            "content_type": "product",
            "contents": [
                {
                    "id": str(item.product_id),
                    "quantity": int(item.quantity),
                    "item_price": int(item.unit_price),
                }
                for item in lines
            ],
            "num_items": sum(int(item.quantity) for item in lines),
            "order_id": order.number,
        },
        "user_data": user_data,
    }
    if tracking is not None and tracking.event_source_url:
        event["event_source_url"] = tracking.event_source_url

    body: dict[str, Any] = {"data": [event]}
    test_code = settings.meta_test_event_code.strip()
    if test_code:
        body["test_event_code"] = test_code
    return body


def schedule_purchase(
    background: BackgroundTasks, order: Order, tracking: OrderTracking | None
) -> None:
    """Queue the Purchase. Does nothing when CAPI is off, and never raises."""
    number = ""
    try:
        number = order.number
        if not enabled():
            return
        body = build_purchase_body(order, tracking)
        background.add_task(send_purchase, number, body)
    except Exception:
        logger.error("meta_capi_schedule_failed", order_number=number)


async def send_purchase(order_number: str, body: dict[str, Any]) -> None:
    """POST one Purchase. Retries network errors, 429 and 5xx. Never raises."""
    try:
        if not enabled():
            return
        await _post_with_retries(order_number, body)
    except Exception:
        logger.error(
            "meta_capi_purchase_failed",
            order_number=order_number,
            error_type="unexpected",
        )


async def _post_with_retries(order_number: str, body: dict[str, Any]) -> None:
    token = settings.meta_capi_token.get_secret_value().strip()
    pixel = settings.meta_pixel_id.strip()
    if not token or not pixel:
        return
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{quote(pixel, safe='')}/events"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await client.post(url, params={"access_token": token}, json=body)
            except httpx.HTTPError:
                if attempt == MAX_ATTEMPTS - 1:
                    logger.error(
                        "meta_capi_purchase_failed",
                        order_number=order_number,
                        error_type="network",
                    )
                    return
            else:
                if response.status_code < 400:
                    logger.info("meta_capi_purchase_sent", order_number=order_number)
                    return
                retryable = response.status_code == 429 or response.status_code >= 500
                if not retryable or attempt == MAX_ATTEMPTS - 1:
                    logger.error(
                        "meta_capi_purchase_failed",
                        order_number=order_number,
                        status_code=response.status_code,
                    )
                    return
            await asyncio.sleep(BACKOFF_SECONDS[attempt])
