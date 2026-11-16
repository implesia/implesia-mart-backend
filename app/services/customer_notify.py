"""Customer messages when an order is confirmed or shipped.

The send runs after the status commit, on a background task. A failure is
logged and written to ``order_activities``. It does not change the status
response. The same status is claimed once, with a conditional update, so a
repeat of that status does not send again.

No SMS or WhatsApp gateway is connected. ``log`` writes the text to the
application log. ``noop`` does nothing. Both still record the result.
A live send needs an SSL Wireless SMS Plus account; those keys are named
in ``.env.example`` and are not read by this process.
"""

import uuid
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.background import BackgroundTasks

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.order import ActivityAction, Order, OrderStatus

logger = get_logger("customer_sms")

SEND_ON = frozenset({OrderStatus.CONFIRMED.value, OrderStatus.SHIPPED.value})
_RESULTS = frozenset({"logged", "skipped", "failed"})

# Tests replace this with a sessionmaker bound to the test engine.
session_factory: async_sessionmaker[AsyncSession] = SessionLocal


class CustomerMessageProvider(Protocol):
    """One way to hand a short text to the customer."""

    name: str

    async def send(self, *, phone: str, text: str) -> str:
        """Return ``logged``, ``skipped``, or ``failed``. Do not raise for a miss."""


class LogCustomerMessageProvider:
    """Record the text. Do not call a network and do not log the full phone."""

    name = "log"

    async def send(self, *, phone: str, text: str) -> str:
        logger.info(
            "customer_sms_logged",
            phone_tail=phone[-4:] if phone else "",
            characters=len(text),
            message=text,
        )
        return "logged"


class NoopCustomerMessageProvider:
    """Drop the text. The activity row still says it was skipped."""

    name = "noop"

    async def send(self, *, phone: str, text: str) -> str:
        del phone, text
        return "skipped"


def get_provider() -> CustomerMessageProvider:
    if settings.customer_sms_provider == "noop":
        return NoopCustomerMessageProvider()
    return LogCustomerMessageProvider()


def _enabled(status: str) -> bool:
    if not settings.customer_sms_enabled:
        return False
    if status == OrderStatus.CONFIRMED.value:
        return settings.customer_sms_on_confirmed
    if status == OrderStatus.SHIPPED.value:
        return settings.customer_sms_on_shipped
    return False


def order_status_url(number: str) -> str | None:
    """``{ADMIN_BASE_URL}/order-status?number=…``. An empty base omits the link."""
    base = settings.admin_base_url.strip().rstrip("/")
    if not base:
        return None
    return f"{base}/order-status?number={quote(number, safe='')}"


def _due(order: Order) -> int:
    if order.due_amount is None:
        advance = int(order.advance_amount or 0)
        return max(int(order.total) - advance, 0)
    return int(order.due_amount)


def build_message(order: Order, status: str) -> str:
    """Short Bengali text. The phone number is not included."""
    link = order_status_url(order.number)
    if status == OrderStatus.SHIPPED.value:
        parts = [f"Implesia: অর্ডার {order.number} পাঠানো হয়েছে।"]
        courier = order.courier_name.strip()
        tracking = order.tracking_number.strip()
        if courier and tracking:
            parts.append(f"কুরিয়ার {courier}, ট্র্যাকিং {tracking}।")
        elif courier:
            parts.append(f"কুরিয়ার {courier}।")
        elif tracking:
            parts.append(f"ট্র্যাকিং {tracking}।")
        if link is not None:
            parts.append(f"স্ট্যাটাস: {link}")
        return " ".join(parts)
    parts = [
        f"Implesia: অর্ডার {order.number} নিশ্চিত।",
        f"মোট ৳{int(order.total)}, বাকি ৳{_due(order)}।",
    ]
    if link is not None:
        parts.append(f"স্ট্যাটাস: {link}")
    return " ".join(parts)


async def _claim(db: AsyncSession, order_id: uuid.UUID, status: str) -> bool:
    """Take the send for this status. False when it was already taken."""
    now = datetime.now(UTC)
    if status == OrderStatus.CONFIRMED.value:
        column_empty = Order.customer_sms_confirmed_at.is_(None)
        assignment = {"customer_sms_confirmed_at": now}
    elif status == OrderStatus.SHIPPED.value:
        column_empty = Order.customer_sms_shipped_at.is_(None)
        assignment = {"customer_sms_shipped_at": now}
    else:
        return False
    claimed = (
        await db.execute(
            update(Order)
            .where(Order.id == order_id, column_empty)
            .values(**assignment)
            .returning(Order.id)
        )
    ).first()
    await db.commit()
    return claimed is not None


async def _record(
    order_id: uuid.UUID,
    order_number: str,
    status: str,
    result: str,
    provider: str,
) -> None:
    """Insert one activity row. Never raises."""
    try:
        from app.services.order_service import log_activity

        async with session_factory() as db:
            log_activity(
                db,
                order_id,
                None,
                ActivityAction.CUSTOMER_MESSAGE,
                f"Customer message {result} for {status}",
                {"status": status, "result": result, "provider": provider},
            )
            await db.commit()
    except Exception:
        logger.error(
            "customer_sms_log_failed",
            order_number=order_number,
            status=status,
            error_type="activity",
        )


async def deliver(
    order_id: uuid.UUID,
    order_number: str,
    status: str,
    phone: str,
    text: str,
) -> None:
    """Send, then record the result. Never raises."""
    provider = get_provider()
    result = "failed"
    try:
        result = await provider.send(phone=phone, text=text)
        if result not in _RESULTS:
            result = "failed"
    except Exception:
        logger.error(
            "customer_sms_failed",
            order_number=order_number,
            status=status,
            error_type="unexpected",
        )
        result = "failed"
    await _record(order_id, order_number, status, result, provider.name)


async def schedule(
    db: AsyncSession,
    background: BackgroundTasks | None,
    order: Order,
    status: str,
) -> None:
    """Claim, then queue the send. Never raises, so the status change stands."""
    number = ""
    try:
        number = order.number
        if order.status != status or status not in SEND_ON:
            return
        if not _enabled(status):
            return
        if not order.phone.strip():
            return
        if background is None:
            return
        if not await _claim(db, order.id, status):
            return
        background.add_task(
            deliver,
            order.id,
            order.number,
            status,
            order.phone,
            build_message(order, status),
        )
    except Exception:
        logger.error("customer_sms_schedule_failed", order_number=number, status=status)
