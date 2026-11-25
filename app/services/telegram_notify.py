"""Telegram alerts for new orders, cancellations, low stock, and unanswered chats.

Sent in the background after the database commit. A network error, timeout,
or exception is logged without the bot token and never changes the API
response. httpx error text can include the request URL (and therefore the
token), so failures log an order number and a status or error kind only.

The new-order alert is claimed with one conditional update of
``orders.telegram_notified_at`` before the HTTP call is queued. The row that
wins that update is the only one that sends. An idempotency-key replay never
reaches the claim.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTasks

from app.core.config import LOW_STOCK_THRESHOLD, settings
from app.core.logging import get_logger
from app.models.order import Order

logger = get_logger("telegram")

HTTP_TIMEOUT = httpx.Timeout(5.0)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.5, 1.0)
# A Telegram retry_after of many minutes must not pin a worker. The order
# response has already been sent; this only bounds the background sleep.
MAX_RETRY_AFTER = 30.0
_PENDING_LOW_STOCK = "telegram_low_stock"
_API = "https://api.telegram.org"


def enabled() -> bool:
    return settings.telegram_enabled


def escape_html(value: str) -> str:
    """Escape text for Telegram HTML parse mode."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attr(value: str) -> str:
    return escape_html(value).replace('"', "&quot;")


def admin_order_url(order_id: uuid.UUID) -> str | None:
    """``{ADMIN_BASE_URL}/admin/orders/{id}``. Empty base means no link.

    The storefront list links to ``/admin/orders/${order.id}`` (the UUID).
    The Next.js segment is named ``[number]``, but ``getOrder`` loads
    ``GET /api/v1/admin/orders/{id}``.
    """
    base = settings.admin_base_url.strip().rstrip("/")
    if not base:
        return None
    return f"{base}/admin/orders/{order_id}"


def admin_conversation_url(conversation_id: uuid.UUID) -> str | None:
    """``{ADMIN_BASE_URL}/admin/communication?id={conversation_id}``."""
    base = settings.admin_base_url.strip().rstrip("/")
    if not base:
        return None
    return f"{base}/admin/communication?id={conversation_id}"


def build_unanswered_chat_message(
    *,
    conversation_id: uuid.UUID,
    customer_name: str,
    customer_phone: str | None,
    order_number: str | None,
    excerpt: str,
) -> str:
    lines = [
        "<b>Unanswered customer chat</b>",
        f"Customer: {escape_html(customer_name)}",
    ]
    if customer_phone:
        lines.append(f"Phone: {escape_html(customer_phone)}")
    if order_number:
        lines.append(f"Order: #{escape_html(order_number)}")
    lines.append(f"Message: {escape_html(excerpt[:300])}")
    url = admin_conversation_url(conversation_id)
    if url is not None:
        lines.append(f'<a href="{_escape_attr(url)}">Open Admin Inbox</a>')
    return "\n".join(lines)


def _due(order: Order) -> int:
    if order.due_amount is None:
        return int(order.total)
    return int(order.due_amount)


def payment_line(order: Order) -> str:
    """COD shows the amount still due. Bangla QR shows advance paid and the rest."""
    due = _due(order)
    if order.payment_method == "bangla_qr":
        return f"Payment: Bangla QR — advance paid ৳{int(order.advance_amount)}, remaining ৳{due}"
    return f"Payment: Cash on delivery — due ৳{due}"


def build_new_order_message(order: Order) -> str:
    lines = [
        f"<b>New order {escape_html(order.number)}</b>",
        f"Customer: {escape_html(order.customer_name)}",
        f"Phone: {escape_html(order.phone)}",
        f"Area: {escape_html(order.area)}",
        "Products:",
    ]
    for item in order.items:
        lines.append(f"• {escape_html(item.title)} × {int(item.quantity)}")
    lines.append(f"Total: ৳{int(order.total)}")
    lines.append(payment_line(order))
    url = admin_order_url(order.id)
    if url is not None:
        lines.append(f'<a href="{_escape_attr(url)}">Open order</a>')
    return "\n".join(lines)


def build_cancelled_message(order: Order) -> str:
    lines = [
        f"<b>Order cancelled {escape_html(order.number)}</b>",
        f"Customer: {escape_html(order.customer_name)}",
        f"Phone: {escape_html(order.phone)}",
        f"Total: ৳{int(order.total)}",
    ]
    url = admin_order_url(order.id)
    if url is not None:
        lines.append(f'<a href="{_escape_attr(url)}">Open order</a>')
    return "\n".join(lines)


def build_low_stock_message(title: str, quantity: int) -> str:
    return (
        f"<b>Low stock</b>\n"
        f"{escape_html(title)} is now {quantity} "
        f"(at or below {LOW_STOCK_THRESHOLD})."
    )


def build_courier_alert_message(
    *,
    order_id: uuid.UUID | None,
    order_number: str,
    status: str,
    consignment_id: str | None = None,
    tracking_message: str = "",
) -> str:
    lines = [
        f"<b>Steadfast alert: {escape_html(status)}</b>",
        f"Order: #{escape_html(order_number)}",
    ]
    if consignment_id:
        lines.append(f"Consignment: {escape_html(consignment_id)}")
    if tracking_message:
        lines.append(f"Message: {escape_html(tracking_message[:300])}")
    if order_id is not None:
        url = admin_order_url(order_id)
        if url is not None:
            lines.append(f'<a href="{_escape_attr(url)}">Open order</a>')
    return "\n".join(lines)


def schedule_courier_alert(
    background: BackgroundTasks | None,
    *,
    order_id: uuid.UUID | None,
    order_number: str,
    status: str,
    consignment_id: str | None = None,
    tracking_message: str = "",
) -> None:
    """Queue a non-blocking Telegram alert for hold/exceptional/partial courier events."""
    if not enabled():
        return
    text = build_courier_alert_message(
        order_id=order_id,
        order_number=order_number,
        status=status,
        consignment_id=consignment_id,
        tracking_message=tracking_message,
    )
    if background is not None:
        background.add_task(send_message, order_number, text)
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(send_message(order_number, text))
    _fallback_tasks.add(task)
    task.add_done_callback(_fallback_tasks.discard)


@dataclass(frozen=True)
class LowStockAlert:
    product_id: uuid.UUID
    title: str
    quantity: int


def discard_low_stock(db: AsyncSession) -> None:
    db.info.pop(_PENDING_LOW_STOCK, None)


def note_low_stock(
    db: AsyncSession,
    *,
    product_id: uuid.UUID,
    title: str,
    before: int | None,
    after: int | None,
) -> None:
    """Remember a product that just crossed from above the threshold to at or below it.

    A sale that stays above the threshold, or that was already at or below it,
    is ignored. NULL stock (made to order) is ignored. The flag defaults off.
    """
    if not settings.telegram_notify_low_stock:
        return
    if before is None or after is None:
        return
    if not (before > LOW_STOCK_THRESHOLD >= after):
        return
    pending: list[LowStockAlert] = db.info.setdefault(_PENDING_LOW_STOCK, [])
    if any(item.product_id == product_id for item in pending):
        return
    pending.append(LowStockAlert(product_id=product_id, title=title, quantity=after))


def flush_low_stock(db: AsyncSession, background: BackgroundTasks | None) -> None:
    """Queue crossed products after a successful commit. Never raises."""
    pending: list[LowStockAlert] = db.info.pop(_PENDING_LOW_STOCK, [])
    if not pending or background is None:
        return
    try:
        if not enabled() or not settings.telegram_notify_low_stock:
            return
        for alert in pending:
            background.add_task(
                send_message,
                "",
                build_low_stock_message(alert.title, alert.quantity),
            )
    except Exception:
        logger.error("telegram_schedule_failed", order_number="", error_type="low_stock")


async def claim_new_order(db: AsyncSession, order_id: uuid.UUID) -> bool:
    """Atomically take the new-order alert. False when it was already claimed or Telegram is off."""
    if not enabled():
        return False
    claimed = (
        await db.execute(
            update(Order)
            .where(Order.id == order_id, Order.telegram_notified_at.is_(None))
            .values(telegram_notified_at=datetime.now(UTC))
            .returning(Order.id)
        )
    ).first()
    await db.commit()
    return claimed is not None


async def notify_new_order(
    db: AsyncSession, background: BackgroundTasks | None, order: Order
) -> None:
    """Claim, then queue the send. A replay or a lost claim does not send. Never raises."""
    number = ""
    try:
        number = order.number
        if background is None or not enabled():
            return
        text = build_new_order_message(order)
        if not await claim_new_order(db, order.id):
            return
        background.add_task(send_message, number, text)
    except Exception:
        logger.error("telegram_schedule_failed", order_number=number)


def schedule_cancelled(background: BackgroundTasks | None, order: Order) -> None:
    """Queue a cancel alert. The status change is already one-shot. Never raises."""
    number = ""
    try:
        number = order.number
        if background is None or not enabled() or not settings.telegram_notify_order_cancelled:
            return
        background.add_task(send_message, number, build_cancelled_message(order))
    except Exception:
        logger.error("telegram_schedule_failed", order_number=number)


def chat_fallback_chat_ids() -> list[str]:
    """Destinations for an unanswered-chat alert.

    A non-empty ``TELEGRAM_CHAT_FALLBACK_CHAT_IDS`` is the only list used.
    An empty or unset list uses ``TELEGRAM_CHAT_IDS``. Order alerts do not
    call this.
    """
    dedicated = [chat for chat in settings.telegram_chat_fallback_chat_ids if chat.strip()]
    if dedicated:
        return dedicated
    return [chat for chat in settings.telegram_chat_ids if chat.strip()]


async def send_message(
    order_number: str, text: str, *, chat_ids: list[str] | None = None
) -> None:
    """POST the text to every chat. Retries network errors, 429, and 5xx. Never raises.

    Order, cancel, and low-stock alerts omit ``chat_ids`` and keep using
    ``TELEGRAM_CHAT_IDS``. The unanswered-chat fallback passes its own list.
    """
    try:
        if not enabled():
            return
        token = settings.telegram_bot_token.get_secret_value().strip()
        source = settings.telegram_chat_ids if chat_ids is None else chat_ids
        chats = [chat for chat in source if chat.strip()]
        if not token or not chats:
            return
        url = f"{_API}/bot{token}/sendMessage"
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            for chat_id in chats:
                await _send_chat(client, url, chat_id, text, order_number)
    except Exception:
        logger.error(
            "telegram_failed",
            order_number=order_number,
            error_type="unexpected",
        )


async def _send_chat(
    client: httpx.AsyncClient,
    url: str,
    chat_id: str,
    text: str,
    order_number: str,
) -> None:
    body = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await client.post(url, json=body)
            except httpx.HTTPError:
                if attempt == MAX_ATTEMPTS - 1:
                    logger.error(
                        "telegram_failed",
                        order_number=order_number,
                        error_type="network",
                    )
                    return
                await asyncio.sleep(BACKOFF_SECONDS[attempt])
                continue
            if response.status_code < 400:
                logger.info("telegram_sent", order_number=order_number)
                return
            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable or attempt == MAX_ATTEMPTS - 1:
                logger.error(
                    "telegram_failed",
                    order_number=order_number,
                    status_code=response.status_code,
                )
                return
            delay: float = BACKOFF_SECONDS[attempt]
            if response.status_code == 429:
                waited = _retry_after_seconds(response)
                if waited is not None:
                    delay = waited
            await asyncio.sleep(delay)
    except Exception:
        logger.error(
            "telegram_failed",
            order_number=order_number,
            error_type="unexpected",
        )


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Telegram sends ``parameters.retry_after`` (seconds). ``Retry-After`` is the fallback."""
    parsed = _retry_after_body(response)
    if parsed is None:
        parsed = _retry_after_header(response)
    if parsed is None or parsed < 0:
        return None
    return min(parsed, MAX_RETRY_AFTER)


def _retry_after_body(response: httpx.Response) -> float | None:
    parse = getattr(response, "json", None)
    if not callable(parse):
        return None
    try:
        body = parse()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    params = body.get("parameters")
    if not isinstance(params, dict) or "retry_after" not in params:
        return None
    return _seconds(params.get("retry_after"))


def _retry_after_header(response: httpx.Response) -> float | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    return _seconds(headers.get("retry-after"))


def _seconds(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


_CHAT_FALLBACK_TTL_SECONDS = 600
_fallback_tasks: set[asyncio.Task[object]] = set()


async def run_unanswered_chat_fallback(
    *,
    conversation_id: uuid.UUID,
    message_created_at: datetime,
    customer_name: str,
    customer_phone: str | None,
    order_number: str | None,
    excerpt: str,
    delay_seconds: int | None = None,
    session_factory: object | None = None,
) -> bool:
    """Wait ``delay_seconds`` then send ONE 1-way Telegram alert if no staff replied."""
    if not settings.telegram_chat_fallback_enabled or not enabled():
        return False

    from sqlalchemy import select as sa_select

    from app.db.session import SessionLocal
    from app.models.communication import Message
    from app.services.redis_client import redis_client

    wait_for = (
        settings.telegram_chat_fallback_delay_seconds
        if delay_seconds is None
        else max(0, delay_seconds)
    )

    claimed = await redis_client.acquire_chat_notify_throttle(
        f"tg:chat_fallback:{conversation_id}",
        "telegram",
        ttl_seconds=_CHAT_FALLBACK_TTL_SECONDS,
    )
    if not claimed:
        return False

    if wait_for > 0:
        await asyncio.sleep(wait_for)

    factory = session_factory or SessionLocal
    async with factory() as db:  # type: ignore[operator]
        staff_reply = await db.scalar(
            sa_select(Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.is_internal_note.is_(False),
                Message.sender_role.notin_(("customer", "seller")),
                Message.created_at >= message_created_at,
            )
            .limit(1)
        )
        if staff_reply is not None:
            return False

    text = build_unanswered_chat_message(
        conversation_id=conversation_id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        order_number=order_number,
        excerpt=excerpt,
    )
    await send_message(
        f"chat:{conversation_id}",
        text,
        chat_ids=chat_fallback_chat_ids(),
    )
    return True


def schedule_unanswered_chat_fallback(
    background: BackgroundTasks | None,
    *,
    conversation_id: uuid.UUID,
    message_created_at: datetime,
    customer_name: str,
    customer_phone: str | None,
    order_number: str | None,
    excerpt: str,
) -> None:
    if not settings.telegram_chat_fallback_enabled or not enabled():
        return
    if background is not None:
        background.add_task(
            run_unanswered_chat_fallback,
            conversation_id=conversation_id,
            message_created_at=message_created_at,
            customer_name=customer_name,
            customer_phone=customer_phone,
            order_number=order_number,
            excerpt=excerpt,
        )
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(
        run_unanswered_chat_fallback(
            conversation_id=conversation_id,
            message_created_at=message_created_at,
            customer_name=customer_name,
            customer_phone=customer_phone,
            order_number=order_number,
            excerpt=excerpt,
        )
    )
    _fallback_tasks.add(task)
    task.add_done_callback(_fallback_tasks.discard)
