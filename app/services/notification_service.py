import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import CustomerNotification
from app.models.order import Order
from app.models.user import User

TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "bn": {
        "new": {
            "title": "অর্ডার গৃহীত হয়েছে",
            "message": "আপনার অর্ডার #{number} সফলভাবে সিস্টেমে যুক্ত হয়েছে। শীঘ্রই ভেরিফিকেশন করা হবে।",
        },
        "confirmed": {
            "title": "অর্ডার কনফার্ম হয়েছে",
            "message": "আপনার অর্ডার #{number} সফলভাবে কনফার্ম করা হয়েছে। শীঘ্রই পার্সেল প্রস্তুত করা হবে।",
        },
        "packed": {
            "title": "অর্ডার প্যাকেজিং সম্পন্ন",
            "message": "আপনার অর্ডার #{number} এর প্যাকেজিং সম্পন্ন হয়েছে এবং কুরিয়ারে হস্তান্তরের অপেক্ষায় আছে।",
        },
        "shipped": {
            "title": "অর্ডার ডেলিভারির পথে",
            "message": (
                "আপনার অর্ডার #{number} কুরিয়ারে হস্তান্তর করা হয়েছে। "
                "কুরিয়ার: {courier} (ট্র্যাকিং: {tracking})।"
            ),
        },
        "delivered": {
            "title": "অর্ডার সফলভাবে পৌঁছেছে",
            "message": (
                "আপনার অর্ডার #{number} সফলভাবে ডেলিভারি সম্পন্ন হয়েছে। "
                "Implesia Mart-এর সাথে থাকার জন্য ধন্যবাদ!"
            ),
        },
        "cancelled": {
            "title": "অর্ডার বাতিল হয়েছে",
            "message": (
                "আপনার অর্ডার #{number} বাতিল করা হয়েছে। "
                "কোনো জিজ্ঞাসা থাকলে আমাদের সাপোর্টে যোগাযোগ করুন।"
            ),
        },
        "returned": {
            "title": "অর্ডার রিটার্ন সম্পন্ন",
            "message": "আপনার অর্ডার #{number} রিটার্ন হিসেবে প্রসেস করা হয়েছে।",
        },
    },
    "en": {
        "new": {
            "title": "Order Placed",
            "message": "Your order #{number} has been placed and is waiting for review.",
        },
        "confirmed": {
            "title": "Order Confirmed",
            "message": "Your order #{number} is confirmed and will be packed shortly.",
        },
        "packed": {
            "title": "Order Packed",
            "message": "Your order #{number} has been packed and ready for dispatch.",
        },
        "shipped": {
            "title": "Order Shipped",
            "message": "Your order #{number} is on the way via {courier} (Tracking: {tracking}).",
        },
        "delivered": {
            "title": "Order Delivered",
            "message": (
                "Your order #{number} has been delivered. "
                "Thank you for shopping with Implesia Mart!"
            ),
        },
        "cancelled": {
            "title": "Order Cancelled",
            "message": (
                "Your order #{number} was cancelled. "
                "Please contact support if you need help."
            ),
        },
        "returned": {
            "title": "Order Returned",
            "message": "Your order #{number} has been returned.",
        },
    },
}


async def create_order_status_notification(
    db: AsyncSession,
    order: Order,
    new_status: str,
    language: str = "bn",
) -> CustomerNotification | None:
    user_id = order.user_id
    if user_id is None and order.phone:
        matched = await db.scalar(select(User.id).where(User.phone == order.phone))
        if matched:
            user_id = matched

    if user_id is None:
        return None

    lang = language.lower() if language.lower() in ("bn", "en") else "bn"
    status_key = new_status.lower()
    tmpl = TEMPLATES.get(lang, TEMPLATES["bn"]).get(
        status_key,
        {
            "title": f"অর্ডার স্ট্যাটাস: {new_status}" if lang == "bn" else f"Order Status: {new_status}",
            "message": f"আপনার অর্ডার #{order.number} এর স্ট্যাটাস পরিবর্তিত হয়ে {new_status} হয়েছে।"
            if lang == "bn"
            else f"Your order #{order.number} status has been updated to {new_status}.",
        },
    )

    courier_text = order.courier_name or ("নির্ধারিত হয়নি" if lang == "bn" else "TBD")
    tracking_text = order.tracking_number or ("প্রযোজ্য নয়" if lang == "bn" else "N/A")

    title = tmpl["title"].format(number=order.number)
    message = tmpl["message"].format(
        number=order.number,
        courier=courier_text,
        tracking=tracking_text,
    )

    notification = CustomerNotification(
        user_id=user_id,
        order_id=order.id,
        type="order_status",
        title=title[:160],
        message=message[:1000],
        language=lang,
        is_read=False,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return notification


async def get_user_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 50,
) -> tuple[list[CustomerNotification], int]:
    cutoff = datetime.now(UTC) - timedelta(days=30)
    stmt = (
        select(CustomerNotification)
        .where(
            CustomerNotification.user_id == user_id,
            CustomerNotification.created_at >= cutoff,
        )
        .order_by(CustomerNotification.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    notifications = list(result.scalars().all())

    unread_stmt = select(func.count(CustomerNotification.id)).where(
        CustomerNotification.user_id == user_id,
        CustomerNotification.is_read.is_(False),
        CustomerNotification.created_at >= cutoff,
    )
    unread_count = (await db.scalar(unread_stmt)) or 0

    return notifications, unread_count


async def purge_expired_notifications(db: AsyncSession) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=30)
    stmt = delete(CustomerNotification).where(CustomerNotification.created_at < cutoff)
    result = await db.execute(stmt)
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def mark_read(
    db: AsyncSession,
    notification_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    stmt = (
        update(CustomerNotification)
        .where(
            CustomerNotification.id == notification_id,
            CustomerNotification.user_id == user_id,
        )
        .values(is_read=True)
    )
    res = await db.execute(stmt)
    await db.commit()
    count = getattr(res, "rowcount", 0) or 0
    return bool(count > 0)


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    stmt = (
        update(CustomerNotification)
        .where(
            CustomerNotification.user_id == user_id,
            CustomerNotification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    res = await db.execute(stmt)
    await db.commit()
    return int(getattr(res, "rowcount", 0) or 0)
