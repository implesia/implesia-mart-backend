"""Own-site customer report for one phone, plus the cached courier check."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.schemas.customer_report import (
    CourierCheck,
    CustomerBrief,
    CustomerReport,
    CustomerReportSummary,
    ReportOrder,
    StatusCounts,
)
from app.schemas.inquiry import normalize_phone
from app.services.courier.provider import success_ratio
from app.services.courier.service import read_courier_check, refresh_courier_check

_ORDER_LIMIT = 50
_STATUSES = tuple(status.value for status in OrderStatus)
_PHONE_MESSAGE = "Use a Bangladeshi mobile number, for example 01712345678."


def require_phone(value: str) -> str:
    phone = normalize_phone(value.strip())
    if phone is None:
        raise UnprocessableError(_PHONE_MESSAGE)
    return phone


async def customer_report(db: AsyncSession, phone_raw: str) -> CustomerReport:
    phone = require_phone(phone_raw)
    customer = await _customer(db, phone)
    summary, orders = await _orders(db, phone)
    courier = await read_courier_check(db, phone)
    return CustomerReport(
        phone=phone,
        customer=customer,
        summary=summary,
        orders=orders,
        courier_check=courier,
    )


async def refresh_courier(db: AsyncSession, phone_raw: str) -> CourierCheck:
    phone = require_phone(phone_raw)
    return await refresh_courier_check(db, phone)


async def _customer(db: AsyncSession, phone: str) -> CustomerBrief | None:
    user = await db.scalar(select(User).where(User.phone == phone))
    if user is None:
        return None
    email = user.email.strip() if isinstance(user.email, str) and user.email.strip() else None
    return CustomerBrief(id=user.id, name=user.full_name, email=email)


async def _orders(db: AsyncSession, phone: str) -> tuple[CustomerReportSummary, list[ReportOrder]]:
    grouped = (
        await db.execute(
            select(
                Order.status,
                Order.origin,
                func.count().label("n"),
                func.coalesce(func.sum(Order.total), 0).label("spent"),
            )
            .where(Order.phone == phone)
            .group_by(Order.status, Order.origin)
        )
    ).all()
    span = (
        await db.execute(
            select(func.min(Order.created_at), func.max(Order.created_at)).where(
                Order.phone == phone
            )
        )
    ).one()
    counts = dict.fromkeys(_STATUSES, 0)
    online = 0
    offline = 0
    total_orders = 0
    total_spent = 0
    for status, origin, count, spent in grouped:
        number = int(count or 0)
        total_orders += number
        if status in counts:
            counts[status] += number
        if origin == "online":
            online += number
        elif origin == "offline":
            offline += number
        if status == OrderStatus.DELIVERED.value:
            total_spent += int(spent or 0)
    delivered = counts[OrderStatus.DELIVERED.value]
    cancelled = counts[OrderStatus.CANCELLED.value]
    returned = counts[OrderStatus.RETURNED.value]
    summary = CustomerReportSummary(
        total_orders=total_orders,
        by_status=StatusCounts(**counts),
        delivered_count=delivered,
        cancelled_count=cancelled,
        returned_count=returned,
        success_rate=success_ratio(delivered, cancelled + returned),
        total_spent=total_spent,
        first_order_at=_moment(span[0]),
        last_order_at=_moment(span[1]),
        online_count=online,
        offline_count=offline,
    )
    rows = (
        await db.scalars(
            select(Order)
            .where(Order.phone == phone)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(_ORDER_LIMIT)
        )
    ).all()
    orders = [
        ReportOrder(
            id=row.id,
            number=row.number,
            status=row.status,
            origin=row.origin,
            total=int(row.total),
            created_at=row.created_at,
            tracking_number=row.tracking_number or "",
        )
        for row in rows
    ]
    return summary, orders


def _moment(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return None
