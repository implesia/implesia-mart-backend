import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.order import ActivityAction, Order, OrderActivity, OrderItem, OrderStatus
from app.models.review import ProductReview
from app.models.user import User
from app.schemas.customer import (
    CustomerDashboardStats,
    OrderTrackingDetail,
    PurchasedProductItem,
    TrackingTimelineStep,
)
from app.services import notification_service, order_service

PURCHASED_STATUSES = {
    OrderStatus.CONFIRMED.value,
    OrderStatus.PACKED.value,
    OrderStatus.SHIPPED.value,
    OrderStatus.DELIVERED.value,
}

ACTIVE_STATUSES = (
    OrderStatus.NEW.value,
    OrderStatus.CONFIRMED.value,
    OrderStatus.PACKED.value,
    OrderStatus.SHIPPED.value,
)

NON_REVENUE_STATUSES = (
    OrderStatus.CANCELLED.value,
    OrderStatus.RETURNED.value,
)

TIMELINE_STEPS = [
    ("new", "অর্ডার প্রাপ্তি", "অর্ডারটি সফলভাবে সিস্টেমে জমা হয়েছে।"),
    ("confirmed", "অর্ডার কনফার্মেশন", "অর্ডারটি যাচাই ও কনফার্ম করা হয়েছে।"),
    ("packed", "প্যাকিং সম্পন্ন", "পার্সেল প্রস্তুত এবং কুরিয়ার ব্যাগে সংরক্ষিত।"),
    ("shipped", "ডেলিভারির পথে", "কুরিয়ার প্রতিনিধির নিকট পার্সেল হস্তান্তর করা হয়েছে।"),
    ("delivered", "ডেলিভারি সম্পন্ন", "গ্রাহকের নিকট সফলভাবে পার্সেল পৌঁছেছে।"),
]

TERMINAL_STEP_META: dict[str, tuple[str, str]] = {
    OrderStatus.CANCELLED.value: ("অর্ডার বাতিল", "অর্ডারটি বাতিল করা হয়েছে।"),
    OrderStatus.RETURNED.value: ("অর্ডার রিটার্ন", "পার্সেলটি রিটার্ন হিসেবে প্রসেস করা হয়েছে।"),
}

STATUS_ORDER = {
    "new": 0,
    "confirmed": 1,
    "packed": 2,
    "shipped": 3,
    "delivered": 4,
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _customer_payment_status(order: Order, paid: int) -> str:
    if paid >= order.total:
        return "paid"
    if paid > 0:
        return "partial"
    if order.payment_method == "cod":
        return "cod_due"
    return "unpaid"


async def get_dashboard_summary(
    db: AsyncSession,
    user: User,
) -> CustomerDashboardStats:
    total_orders = (
        await db.scalar(select(func.count(Order.id)).where(Order.user_id == user.id))
    ) or 0

    active_orders = (
        await db.scalar(
            select(func.count(Order.id)).where(
                Order.user_id == user.id, Order.status.in_(ACTIVE_STATUSES)
            )
        )
    ) or 0

    delivered_orders = (
        await db.scalar(
            select(func.count(Order.id)).where(
                Order.user_id == user.id, Order.status == OrderStatus.DELIVERED.value
            )
        )
    ) or 0

    cancelled_orders = (
        await db.scalar(
            select(func.count(Order.id)).where(
                Order.user_id == user.id, Order.status == OrderStatus.CANCELLED.value
            )
        )
    ) or 0

    total_products_purchased = (
        await db.scalar(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.user_id == user.id, Order.status.notin_(NON_REVENUE_STATUSES))
        )
    ) or 0

    total_spent = (
        await db.scalar(
            select(func.coalesce(func.sum(Order.total), 0)).where(
                Order.user_id == user.id, Order.status.notin_(NON_REVENUE_STATUSES)
            )
        )
    ) or 0

    unread_notifications = await notification_service.count_unread_notifications(db, user.id)

    return CustomerDashboardStats(
        total_orders=int(total_orders),
        active_orders=int(active_orders),
        delivered_orders=int(delivered_orders),
        cancelled_orders=int(cancelled_orders),
        total_products_purchased=int(total_products_purchased),
        unread_notifications=int(unread_notifications),
        total_spent=int(total_spent),
        customer_name=user.full_name,
        phone=user.phone,
        email=user.email,
    )


async def get_purchased_products(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[PurchasedProductItem]:
    # 1. Fetch user orders that are confirmed or completed
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(
            Order.user_id == user_id,
            Order.status.in_(PURCHASED_STATUSES),
        )
        .order_by(Order.created_at.desc())
    )
    result = await db.execute(stmt)
    orders = list(result.scalars().all())

    # 2. Collect user reviews to determine can_review
    rev_stmt = select(ProductReview.product_id).where(ProductReview.user_id == user_id)
    rev_res = await db.execute(rev_stmt)
    reviewed_product_ids = set(rev_res.scalars().all())

    items: list[PurchasedProductItem] = []

    for order in orders:
        paid = order_service.effective_paid(order)
        due = (
            int(order.due_amount)
            if order.due_amount is not None
            else max(int(order.total) - paid, 0)
        )
        payment_status = _customer_payment_status(order, paid)

        for item in order.items:
            if item.product_id is None:
                continue

            items.append(
                PurchasedProductItem(
                    product_id=item.product_id,
                    title=item.title,
                    slug=item.slug,
                    image_url=item.image_src,
                    price=item.unit_price,
                    quantity=item.quantity,
                    line_total=item.line_total,
                    purchased_at=order.created_at,
                    order_number=order.number,
                    order_status=order.status,
                    payment_method=order.payment_method,
                    paid_amount=paid,
                    due_amount=due,
                    payment_status=payment_status,
                    can_review=item.product_id not in reviewed_product_ids,
                )
            )

    return items


async def get_order_tracking(
    db: AsyncSession,
    user_id: uuid.UUID,
    order_number: str,
) -> OrderTrackingDetail:
    stmt = select(Order).where(Order.number == order_number, Order.user_id == user_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found")

    activity_rows = (
        (
            await db.execute(
                select(OrderActivity)
                .where(
                    OrderActivity.order_id == order.id,
                    OrderActivity.action == ActivityAction.STATUS_CHANGED.value,
                )
                .order_by(OrderActivity.created_at.asc(), OrderActivity.id.asc())
            )
        )
        .scalars()
        .all()
    )

    step_timestamps: dict[str, datetime] = {
        OrderStatus.NEW.value: _as_utc(order.created_at),
    }
    max_reached_idx = 0

    for row in activity_rows:
        detail = row.detail or {}
        src = detail.get("from")
        dst = detail.get("to")
        if isinstance(src, str) and src.lower() in STATUS_ORDER:
            max_reached_idx = max(max_reached_idx, STATUS_ORDER[src.lower()])
        if isinstance(dst, str) and dst:
            dst_key = dst.lower()
            step_timestamps.setdefault(dst_key, _as_utc(row.created_at))
            if dst_key in STATUS_ORDER:
                max_reached_idx = max(max_reached_idx, STATUS_ORDER[dst_key])

    if order.delivered_at is not None:
        step_timestamps.setdefault(OrderStatus.DELIVERED.value, _as_utc(order.delivered_at))
        max_reached_idx = max(max_reached_idx, STATUS_ORDER[OrderStatus.DELIVERED.value])
    if order.returned_at is not None:
        step_timestamps.setdefault(OrderStatus.RETURNED.value, _as_utc(order.returned_at))

    status_lower = order.status.lower()
    timeline: list[TrackingTimelineStep] = []

    if status_lower in TERMINAL_STEP_META:
        reached_idx = (
            max(max_reached_idx, STATUS_ORDER[OrderStatus.SHIPPED.value])
            if status_lower == OrderStatus.RETURNED.value
            else max_reached_idx
        )
        for step_status, label, desc in TIMELINE_STEPS:
            if STATUS_ORDER[step_status] <= reached_idx:
                timeline.append(
                    TrackingTimelineStep(
                        status=step_status,
                        label=label,
                        description=desc,
                        timestamp=step_timestamps.get(step_status),
                        completed=True,
                    )
                )
        term_label, term_desc = TERMINAL_STEP_META[status_lower]
        timeline.append(
            TrackingTimelineStep(
                status=status_lower,
                label=term_label,
                description=term_desc,
                timestamp=step_timestamps.get(status_lower),
                completed=True,
            )
        )
    else:
        current_idx = STATUS_ORDER.get(status_lower, 0)
        for step_status, label, desc in TIMELINE_STEPS:
            step_idx = STATUS_ORDER[step_status]
            completed = step_idx <= current_idx
            timeline.append(
                TrackingTimelineStep(
                    status=step_status,
                    label=label,
                    description=desc,
                    timestamp=step_timestamps.get(step_status) if completed else None,
                    completed=completed,
                )
            )

    return OrderTrackingDetail(
        order_number=order.number,
        status=order.status,
        courier_name=order.courier_name or "",
        tracking_number=order.tracking_number or "",
        tracking_url=None,
        live_events=[],
        timeline=timeline,
    )
