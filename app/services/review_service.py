import uuid

from sqlalchemy import ColumnElement, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.review import ProductReview
from app.models.user import User
from app.schemas.review import (
    AdminProductReviewSummaryList,
    AdminProductReviewSummaryRow,
    AdminReviewCustomerInfo,
    AdminReviewListResponse,
    AdminReviewOverview,
    AdminReviewProductInfo,
    AdminReviewRead,
    AdminReviewUpdate,
    CanReviewResponse,
    ProductReviewCreate,
    ProductReviewPage,
    ProductReviewRead,
    ProductReviewSummary,
)
from app.services import audit_service

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


def _to_admin_review(review: ProductReview, product: Product, user: User) -> AdminReviewRead:
    return AdminReviewRead(
        id=review.id,
        rating=review.rating,
        headline=review.headline,
        comment=review.comment,
        is_verified_purchase=review.is_verified_purchase,
        is_published=review.is_published,
        created_at=review.created_at,
        updated_at=review.updated_at,
        product=AdminReviewProductInfo(
            id=product.id,
            name=product.title,
            slug=product.slug,
            thumbnail=product.image_src or None,
        ),
        customer=AdminReviewCustomerInfo(
            id=user.id,
            full_name=user.full_name,
            phone=user.phone,
            avatar_url=user.avatar_url,
        ),
    )


async def get_admin_overview(db: AsyncSession) -> AdminReviewOverview:
    agg = (
        await db.execute(
            select(
                func.count(ProductReview.id).label("total"),
                func.coalesce(func.avg(ProductReview.rating), 0).label("avg_rating"),
                func.coalesce(
                    func.sum(case((ProductReview.is_published.is_(True), 1), else_=0)), 0
                ).label("published_count"),
                func.coalesce(
                    func.sum(case((ProductReview.is_published.is_(False), 1), else_=0)), 0
                ).label("hidden_count"),
                func.count(func.distinct(ProductReview.product_id)).label("products_count"),
            )
        )
    ).one()

    total = int(agg.total or 0)
    avg_rating = round(float(agg.avg_rating or 0), 2)
    published_count = int(agg.published_count or 0)
    hidden_count = int(agg.hidden_count or 0)
    products_count = int(agg.products_count or 0)

    dist_rows = (
        await db.execute(
            select(ProductReview.rating, func.count(ProductReview.id)).group_by(
                ProductReview.rating
            )
        )
    ).all()
    counts = {int(rating): int(cnt) for rating, cnt in dist_rows}
    distribution = {str(star): counts.get(star, 0) for star in range(1, 6)}
    five_star_percent = round((counts.get(5, 0) / total) * 100, 1) if total > 0 else 0.0

    recent_rows = (
        await db.execute(
            select(ProductReview, Product, User)
            .join(Product, Product.id == ProductReview.product_id)
            .join(User, User.id == ProductReview.user_id)
            .order_by(ProductReview.created_at.desc())
            .limit(10)
        )
    ).all()
    recent = [_to_admin_review(rev, prod, usr) for rev, prod, usr in recent_rows]

    return AdminReviewOverview(
        total_reviews=total,
        average_rating=avg_rating,
        published_count=published_count,
        hidden_count=hidden_count,
        five_star_percent=five_star_percent,
        rating_distribution=distribution,
        products_with_reviews_count=products_count,
        recent_reviews=recent,
    )


async def list_admin_reviews(
    db: AsyncSession,
    *,
    product_id: uuid.UUID | None = None,
    rating: int | None = None,
    is_published: bool | None = None,
    q: str | None = None,
    sort: str = "newest",
    page: int = 1,
    page_size: int = 20,
) -> AdminReviewListResponse:
    conditions: list[ColumnElement[bool]] = []
    if product_id is not None:
        conditions.append(ProductReview.product_id == product_id)
    if rating is not None:
        conditions.append(ProductReview.rating == rating)
    if is_published is not None:
        conditions.append(ProductReview.is_published.is_(is_published))
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                ProductReview.headline.ilike(pattern),
                ProductReview.comment.ilike(pattern),
                User.full_name.ilike(pattern),
                Product.title.ilike(pattern),
            )
        )

    count_stmt = (
        select(func.count(ProductReview.id))
        .join(Product, Product.id == ProductReview.product_id)
        .join(User, User.id == ProductReview.user_id)
    )
    list_stmt = (
        select(ProductReview, Product, User)
        .join(Product, Product.id == ProductReview.product_id)
        .join(User, User.id == ProductReview.user_id)
    )
    if conditions:
        count_stmt = count_stmt.where(*conditions)
        list_stmt = list_stmt.where(*conditions)

    if sort == "oldest":
        ordered_stmt = list_stmt.order_by(ProductReview.created_at.asc())
    elif sort == "highest":
        ordered_stmt = list_stmt.order_by(
            ProductReview.rating.desc(), ProductReview.created_at.desc()
        )
    elif sort == "lowest":
        ordered_stmt = list_stmt.order_by(
            ProductReview.rating.asc(), ProductReview.created_at.desc()
        )
    else:
        ordered_stmt = list_stmt.order_by(ProductReview.created_at.desc())

    total = int((await db.scalar(count_stmt)) or 0)
    offset = (page - 1) * page_size
    rows = (await db.execute(ordered_stmt.offset(offset).limit(page_size))).all()
    items = [_to_admin_review(rev, prod, usr) for rev, prod, usr in rows]
    pages = (total + page_size - 1) // page_size if total > 0 else 1
    return AdminReviewListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


async def list_admin_reviews_by_product(
    db: AsyncSession,
    *,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> AdminProductReviewSummaryList:
    conditions: list[ColumnElement[bool]] = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(or_(Product.title.ilike(pattern), Product.slug.ilike(pattern)))

    count_stmt = select(func.count(func.distinct(ProductReview.product_id))).join(
        Product, Product.id == ProductReview.product_id
    )
    if conditions:
        count_stmt = count_stmt.where(*conditions)
    total = int((await db.scalar(count_stmt)) or 0)

    latest_col = func.max(ProductReview.created_at).label("latest_review_at")
    stmt = (
        select(
            Product.id.label("product_id"),
            Product.title.label("name"),
            Product.slug.label("slug"),
            Product.image_src.label("thumbnail"),
            func.count(ProductReview.id).label("review_count"),
            func.coalesce(func.avg(ProductReview.rating), 0).label("average_rating"),
            func.coalesce(
                func.sum(case((ProductReview.is_published.is_(True), 1), else_=0)), 0
            ).label("published_count"),
            func.coalesce(
                func.sum(case((ProductReview.is_published.is_(False), 1), else_=0)), 0
            ).label("hidden_count"),
            latest_col,
        )
        .join(Product, Product.id == ProductReview.product_id)
        .group_by(Product.id, Product.title, Product.slug, Product.image_src)
        .order_by(latest_col.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if conditions:
        stmt = stmt.where(*conditions)

    rows = (await db.execute(stmt)).all()
    items = [
        AdminProductReviewSummaryRow(
            product_id=row.product_id,
            name=row.name,
            slug=row.slug,
            thumbnail=row.thumbnail or None,
            review_count=int(row.review_count or 0),
            average_rating=round(float(row.average_rating or 0), 2),
            published_count=int(row.published_count or 0),
            hidden_count=int(row.hidden_count or 0),
            latest_review_at=row.latest_review_at,
        )
        for row in rows
    ]
    pages = (total + page_size - 1) // page_size if total > 0 else 1
    return AdminProductReviewSummaryList(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


async def update_admin_review(
    db: AsyncSession,
    review_id: uuid.UUID,
    payload: AdminReviewUpdate,
    *,
    actor: User,
) -> AdminReviewRead:
    row = (
        await db.execute(
            select(ProductReview, Product, User)
            .join(Product, Product.id == ProductReview.product_id)
            .join(User, User.id == ProductReview.user_id)
            .where(ProductReview.id == review_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Review not found")

    review, product, customer = row
    data = payload.model_dump(exclude_unset=True)
    changes: dict[str, object] = {}
    if "rating" in data and data["rating"] is not None:
        review.rating = int(data["rating"])
        changes["rating"] = review.rating
    if "headline" in data and data["headline"] is not None:
        review.headline = str(data["headline"]).strip()
        changes["headline"] = review.headline
    if "comment" in data and data["comment"] is not None:
        review.comment = str(data["comment"]).strip()
        changes["comment"] = review.comment
    if "is_published" in data and data["is_published"] is not None:
        review.is_published = bool(data["is_published"])
        changes["is_published"] = review.is_published

    await audit_service.record(
        db,
        actor_id=actor.id,
        action="REVIEW_UPDATED",
        target_type="product_review",
        target_id=review.id,
        metadata={"product_id": str(product.id), "changes": changes},
    )
    await db.commit()
    await db.refresh(review)
    return _to_admin_review(review, product, customer)


async def delete_admin_review(
    db: AsyncSession,
    review_id: uuid.UUID,
    *,
    actor: User,
) -> None:
    review = await db.get(ProductReview, review_id)
    if review is None:
        raise NotFoundError("Review not found")

    product_id = str(review.product_id)
    rating = review.rating
    await db.delete(review)
    await audit_service.record(
        db,
        actor_id=actor.id,
        action="REVIEW_DELETED",
        target_type="product_review",
        target_id=review_id,
        metadata={"product_id": product_id, "rating": rating},
    )
    await db.commit()
