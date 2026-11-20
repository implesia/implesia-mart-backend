import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.order import Order, OrderStatus
from app.models.review import ProductReview
from app.schemas.customer import OrderTrackingDetail, PurchasedProductItem, TrackingTimelineStep

PURCHASED_STATUSES = {
    OrderStatus.CONFIRMED.value,
    OrderStatus.PACKED.value,
    OrderStatus.SHIPPED.value,
    OrderStatus.DELIVERED.value,
}

TIMELINE_STEPS = [
    ("new", "অর্ডার প্রাপ্তি", "অর্ডারটি সফলভাবে সিস্টেমে জমা হয়েছে।"),
    ("confirmed", "অর্ডার কনফার্মেশন", "অর্ডারটি যাচাই ও কনফার্ম করা হয়েছে।"),
    ("packed", "প্যাকিং সম্পন্ন", "পার্সেল প্রস্তুত এবং কুরিয়ার ব্যাগে সংরক্ষিত।"),
    ("shipped", "ডেলিভারির পথে", "কুরিয়ার প্রতিনিধির নিকট পার্সেল হস্তান্তর করা হয়েছে।"),
    ("delivered", "ডেলিভারি সম্পন্ন", "গ্রাহকের নিকট সফলভাবে পার্সেল পৌঁছেছে।"),
]

STATUS_ORDER = {
    "new": 0,
    "confirmed": 1,
    "packed": 2,
    "shipped": 3,
    "delivered": 4,
}


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

    seen_products: set[uuid.UUID] = set()
    items: list[PurchasedProductItem] = []

    for order in orders:
        for item in order.items:
            if item.product_id is None or item.product_id in seen_products:
                continue
            seen_products.add(item.product_id)

            items.append(
                PurchasedProductItem(
                    product_id=item.product_id,
                    title=item.title,
                    slug=item.slug,
                    image_url=item.image_src,
                    price=item.unit_price,
                    purchased_at=order.created_at,
                    order_number=order.number,
                    payment_method=order.payment_method,
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

    current_idx = STATUS_ORDER.get(order.status.lower(), 0)
    timeline: list[TrackingTimelineStep] = []

    for step_status, label, desc in TIMELINE_STEPS:
        step_idx = STATUS_ORDER[step_status]
        completed = step_idx <= current_idx
        ts = None
        if step_status == "new":
            ts = order.created_at
        elif step_status == "delivered" and order.status == "delivered":
            ts = order.delivered_at or order.updated_at
        elif completed:
            ts = order.updated_at

        timeline.append(
            TrackingTimelineStep(
                status=step_status,
                label=label,
                description=desc,
                timestamp=ts,
                completed=completed,
            )
        )

    return OrderTrackingDetail(
        order_number=order.number,
        status=order.status,
        courier_name=order.courier_name or "",
        tracking_number=order.tracking_number or "",
        timeline=timeline,
    )
