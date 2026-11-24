"""Meta Conversions API Purchase events.

Sent once, after a new online order is committed. Offline and admin-created
orders never send. A failure here must not change the order response. The
access token and raw phone, email, name, address, IP, and user agent are never
logged: httpx error text can include the request URL, so failures log the
order number and a status or error kind only.

``user_data`` match fields:

- ``ph``, ``em``, ``fn``, ``ln``, ``ct``, ``country``, ``external_id`` are
  SHA-256 hex after Meta's normalization. ``ct`` and ``country`` are
  lowercased and trimmed, then punctuation and spaces are removed. ``country``
  is always ``bd``. Phone is ``8801XXXXXXXXX``.
- ``client_ip_address`` and ``client_user_agent`` are sent as-is, not hashed.
  The IP is ``CF-Connecting-IP``, else the first ``X-Forwarded-For`` entry,
  else the request client host.
- ``fbp`` and ``fbc`` are the browser cookie values, not hashed.
- ``external_id`` is the customer id when the order has one, otherwise the
  normalized phone for a guest.

The Purchase ``event_id`` is ``purchase_<order_number>``. When
``META_TEST_EVENT_CODE`` is set, the body includes ``test_event_code``.
"""

import asyncio
import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from starlette.background import BackgroundTasks
from starlette.requests import Request

from app.core.config import settings
from app.core.logging import get_logger
from app.models.order import Order, OrderItem, OrderOrigin
from app.schemas.order import OrderTracking, purchase_event_id

logger = get_logger("meta_capi")

# Graph API version is fixed here. It is not an environment variable.
GRAPH_API_VERSION = "v21.0"
HTTP_TIMEOUT = httpx.Timeout(5.0)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.5, 1.0)
_COUNTRY = "bd"

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


def _without_punctuation(value: str) -> str:
    """Drop punctuation and spaces. Letters, including Bengali vowel signs, stay."""
    return "".join(
        char for char in value if unicodedata.category(char)[0] not in {"P", "Z"}
    )


def normalize_location(value: str) -> str | None:
    """Meta ``ct`` / ``country``: trim, lowercase, drop punctuation and spaces."""
    cleaned = _without_punctuation(value.strip().lower())
    return cleaned or None


def hash_location(value: str) -> str | None:
    normalized = normalize_location(value)
    if normalized is None:
        return None
    return _sha256(normalized)


def name_parts(name: str) -> tuple[str | None, str | None]:
    """First and last name for ``fn`` / ``ln``.

    Lowercased, punctuation removed. The first word is ``fn``. When there is
    more than one word, the last word is ``ln``.
    """
    parts: list[str] = []
    for raw in name.strip().lower().split():
        cleaned = _without_punctuation(raw)
        if cleaned:
            parts.append(cleaned)
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]


def hash_external_id(value: str) -> str | None:
    """SHA-256 of a trimmed, lowercased id. Hyphens in a UUID are kept."""
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    return _sha256(cleaned)


def client_ip_address(request: Request) -> str | None:
    """Visitor IP for Meta. Not the rate-limit address.

    ``CF-Connecting-IP`` wins. Otherwise the first ``X-Forwarded-For`` entry.
    Otherwise the socket client host. Empty values are skipped.
    """
    cloudflare = _header_token(request.headers.get("cf-connecting-ip"))
    if cloudflare:
        return cloudflare
    forwarded = request.headers.get("x-forwarded-for") or ""
    first = _header_token(forwarded.split(",", 1)[0] if forwarded else "")
    if first:
        return first
    if request.client is None:
        return None
    return _header_token(request.client.host)


def client_user_agent(request: Request) -> str | None:
    """``User-Agent`` as sent, trimmed. Not hashed. Omitted when blank."""
    return _header_token(request.headers.get("user-agent"))


def _header_token(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _event_time(created: datetime | None) -> int:
    if not isinstance(created, datetime):
        return int(datetime.now(UTC).timestamp())
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return int(created.timestamp())


def _lines(items: list[OrderItem]) -> list[OrderItem]:
    return [item for item in items if item.product_id is not None]


def _external_id(order: Order) -> str | None:
    # Column values already on the instance. Do not lazy-load in this sync helper.
    user_id = order.__dict__.get("user_id")
    if user_id is not None:
        return hash_external_id(str(user_id))
    normalized = normalize_phone(order.phone or "")
    if normalized is None:
        return None
    return _sha256(normalized)


def _put_hash(user_data: dict[str, Any], key: str, hashed: str | None) -> None:
    if hashed is not None:
        user_data[key] = [hashed]


def build_purchase_body(
    order: Order,
    tracking: OrderTracking | None,
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Graph API body for one Purchase.

    Hashed: phone, email, first and last name, district (``ct``), country
    ``bd``, and ``external_id``. Not hashed: ``fbp``, ``fbc``, client IP, and
    user agent. Street address, area, and notes are not sent.
    """
    lines = _lines(list(order.items))
    user_data: dict[str, Any] = {}
    _put_hash(user_data, "ph", hash_phone(order.phone))
    _put_hash(user_data, "em", hash_email(order.email or ""))
    first, last = name_parts(order.customer_name or "")
    _put_hash(user_data, "fn", _sha256(first) if first else None)
    _put_hash(user_data, "ln", _sha256(last) if last else None)
    _put_hash(user_data, "ct", hash_location(order.district or ""))
    _put_hash(user_data, "country", hash_location(_COUNTRY))
    _put_hash(user_data, "external_id", _external_id(order))
    ip_address = _header_token(client_ip)
    if ip_address:
        user_data["client_ip_address"] = ip_address
    agent = _header_token(user_agent)
    if agent:
        user_data["client_user_agent"] = agent
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
    if order.coupon_code:
        event["custom_data"]["coupon"] = order.coupon_code
    if tracking is not None and tracking.event_source_url:
        event["event_source_url"] = tracking.event_source_url

    body: dict[str, Any] = {"data": [event]}
    test_code = settings.meta_test_event_code.strip()
    if test_code:
        body["test_event_code"] = test_code
    return body


def schedule_purchase(
    background: BackgroundTasks,
    order: Order,
    tracking: OrderTracking | None,
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Queue the Purchase. Offline orders and a disabled CAPI send nothing.

    Never raises. A replay or a status change does not call this.
    """
    number = ""
    try:
        number = order.number
        if not enabled() or order.__dict__.get("origin") == OrderOrigin.OFFLINE.value:
            return
        body = build_purchase_body(
            order,
            tracking,
            client_ip=client_ip,
            user_agent=user_agent,
        )
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
