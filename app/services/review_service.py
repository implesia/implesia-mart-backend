import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, UnprocessableError
from app.models.order import Order, OrderItem, OrderStatus
from app.models.review import ProductReview
from app.models.user import User
from app.schemas.review import (
    CanReviewResponse,
    ProductReviewCreate,
    ProductReviewPage,
    ProductReviewRead,
    ProductReviewSummary,
)

ELIGIBLE_STATUSES = {
    OrderStatus.CONFIRMED.value,
    OrderStatus.PACKED.value,
    OrderStatus.SHIPPED.value,
    OrderStatus.DELIVERED.value,
}


async def verify_purchaser(
    db: AsyncSession,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
) -> CanReviewResponse:
    # 1. Check if user already submitted a review for this product
    existing = await db.scalar(
        select(ProductReview.id).where(
            ProductReview.user_id == user_id,
            ProductReview.product_id == product_id,
        )
    )
    if existing:
        return CanReviewResponse(
            can_review=False,
            reason="আপনি ইতিমধ্যে এই পণ্যটির রিভিউ প্রদান করেছেন।",
        )

    # 2. Check if user has an eligible order containing this product
    stmt = (
        select(Order.id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(
            Order.user_id == user_id,
            OrderItem.product_id == product_id,
            Order.status.in_(ELIGIBLE_STATUSES),
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    order_id = await db.scalar(stmt)
    if not order_id:
        return CanReviewResponse(
            can_review=False,
            reason="শুধুমাত্র পণ্যটি সফলভাবে অর্ডারকারী গ্রাহকগণ রিভিউ দিতে পারেন।",
        )

    return CanReviewResponse(
        can_review=True,
        reason="আপনি এই পণ্যটির রিভিউ দিতে প্রস্তুত।",
        order_id=order_id,
    )


async def submit_review(
    db: AsyncSession,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: ProductReviewCreate,
) -> ProductReviewRead:
    check = await verify_purchaser(db, user_id, product_id)
    if not check.can_review:
        raise ConflictError(check.reason)

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise UnprocessableError("User not found")

    review = ProductReview(
        product_id=product_id,
        user_id=user_id,
        order_id=check.order_id,
        rating=payload.rating,
        headline=payload.headline.strip(),
        comment=payload.comment.strip(),
        is_verified_purchase=True,
        is_published=True,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)

    return ProductReviewRead(
        id=review.id,
        product_id=review.product_id,
        user_id=review.user_id,
        user_name=user.full_name,
        user_avatar=user.avatar_url,
        rating=review.rating,
        headline=review.headline,
        comment=review.comment,
        is_verified_purchase=review.is_verified_purchase,
        created_at=review.created_at,
    )


async def get_review_summary(
    db: AsyncSession,
    product_id: uuid.UUID,
) -> ProductReviewSummary:
    stmt = select(
        func.count(ProductReview.id),
        func.coalesce(func.avg(ProductReview.rating), 0),
    ).where(
        ProductReview.product_id == product_id,
        ProductReview.is_published.is_(True),
    )
    res = await db.execute(stmt)
    row = res.one()
    total = int(row[0] or 0)
    avg_rating = round(float(row[1] or 0), 1)

    # Histogram
    hist_stmt = (
        select(ProductReview.rating, func.count(ProductReview.id))
        .where(
            ProductReview.product_id == product_id,
            ProductReview.is_published.is_(True),
        )
        .group_by(ProductReview.rating)
    )
    hist_res = await db.execute(hist_stmt)
    counts = dict(hist_res.all())
    histogram = {str(r): counts.get(r, 0) for r in range(1, 6)}

    return ProductReviewSummary(
        average_rating=avg_rating,
        total_reviews=total,
        rating_histogram=histogram,
    )


async def get_product_reviews(
    db: AsyncSession,
    product_id: uuid.UUID,
    page: int = 1,
    page_size: int = 10,
) -> ProductReviewPage:
    offset = (page - 1) * page_size
    stmt = (
        select(ProductReview)
        .options(selectinload(ProductReview.user))
        .where(
            ProductReview.product_id == product_id,
            ProductReview.is_published.is_(True),
        )
        .order_by(ProductReview.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    reviews = list(result.scalars().all())

    summary = await get_review_summary(db, product_id)
    items = [
        ProductReviewRead(
            id=r.id,
            product_id=r.product_id,
            user_id=r.user_id,
            user_name=r.user.full_name if r.user else "Customer",
            user_avatar=r.user.avatar_url if r.user else None,
            rating=r.rating,
            headline=r.headline,
            comment=r.comment,
            is_verified_purchase=r.is_verified_purchase,
            created_at=r.created_at,
        )
        for r in reviews
    ]

    pages = (summary.total_reviews + page_size - 1) // page_size if summary.total_reviews > 0 else 1

    return ProductReviewPage(
        items=items,
        summary=summary,
        total=summary.total_reviews,
        page=page,
        page_size=page_size,
        pages=pages,
    )
