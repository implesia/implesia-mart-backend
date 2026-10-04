import uuid

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.home.review import HomeReview, HomeReviewItem
from app.schemas.home.review import (
    ReviewAdmin,
    ReviewCopyUpdate,
    ReviewItemPublic,
    ReviewItemRead,
    ReviewItemUpdate,
    ReviewItemWrite,
    ReviewPublic,
    ReviewReorder,
)
from app.services.image_storage import delete_owned_media, owned_refs, read_image, store_image

REVIEW_SLUG = "home"
MAX_ITEMS = 24
_MEDIA = "reviews"
DEFAULT_KICKER = "রিভিউ"
DEFAULT_TITLE = "কাস্টমাররা যা বলছেন"
DEFAULT_SUBTITLE = "হোয়াটসঅ্যাপ ও মেসেঞ্জারের রিভিউ স্ক্রিনশট। ছবিতে ক্লিক করলে পুরো কথোপকথন খোলে।"
DEFAULTS: tuple[dict[str, object], ...] = (
    {
        "product": "সানসেট ল্যাম্প",
        "channel": "WhatsApp",
        "image_src": "/images/reviews/sunset-lamp-1.jpg",
        "image_alt": "সানসেট ল্যাম্পের কাস্টমার রিভিউ স্ক্রিনশট",
        "sort_order": 0,
    },
    {
        "product": "AI ফোন হোল্ডার",
        "channel": "Messenger",
        "image_src": "/images/reviews/phone-holder-1.jpg",
        "image_alt": "এআই ফোন হোল্ডারের কাস্টমার রিভিউ স্ক্রিনশট",
        "sort_order": 1,
    },
    {
        "product": "কাস্টম গাউন",
        "channel": "WhatsApp",
        "image_src": "/images/reviews/gown-1.jpg",
        "image_alt": "কাস্টম গাউনের কাস্টমার রিভিউ স্ক্রিনশট",
        "sort_order": 2,
    },
    {
        "product": "AI ফোন হোল্ডার",
        "channel": "WhatsApp",
        "image_src": "/images/reviews/phone-holder-2.jpg",
        "image_alt": "এআই ফোন হোল্ডারের আরেকটি কাস্টমার রিভিউ স্ক্রিনশট",
        "sort_order": 3,
    },
    {
        "product": "সানসেট ল্যাম্প",
        "channel": "Messenger",
        "image_src": "/images/reviews/sunset-lamp-2.jpg",
        "image_alt": "সানসেট ল্যাম্পের আরেকটি কাস্টমার রিভিউ স্ক্রিনশট",
        "sort_order": 4,
    },
    {
        "product": "বেবি পার্টি ফ্রক",
        "channel": "WhatsApp",
        "image_src": "/images/reviews/baby-frock-1.jpg",
        "image_alt": "বেবি পার্টি ফ্রকের কাস্টমার রিভিউ স্ক্রিনশট",
        "sort_order": 5,
    },
)


def present(item: HomeReviewItem) -> ReviewItemRead:
    return ReviewItemRead.model_validate(item)


def _reject_staged_path(src: str | None) -> None:
    if src and (src.startswith("/uploads/") or src.startswith("blob:")):
        raise UnprocessableError("Send the image file with the review")


async def _items(
    db: AsyncSession, review_id: uuid.UUID, *, active_only: bool
) -> list[HomeReviewItem]:
    query = select(HomeReviewItem).where(HomeReviewItem.review_id == review_id)
    if active_only:
        query = query.where(HomeReviewItem.is_active.is_(True))
    query = query.order_by(HomeReviewItem.sort_order, HomeReviewItem.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_reviews(db: AsyncSession) -> HomeReview:
    row = await db.scalar(select(HomeReview).where(HomeReview.slug == REVIEW_SLUG))
    if row is not None:
        return row
    row = HomeReview(
        slug=REVIEW_SLUG,
        kicker=DEFAULT_KICKER,
        title=DEFAULT_TITLE,
        subtitle=DEFAULT_SUBTITLE,
    )
    db.add(row)
    await db.flush()
    for raw in DEFAULTS:
        db.add(HomeReviewItem(review_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> ReviewAdmin:
    row = await ensure_reviews(db)
    items = await _items(db, row.id, active_only=False)
    return ReviewAdmin(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        items=[present(item) for item in items],
    )


async def public_view(db: AsyncSession) -> ReviewPublic:
    row = await ensure_reviews(db)
    items = await _items(db, row.id, active_only=True)
    return ReviewPublic(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        items=[
            ReviewItemPublic(
                id=item.id,
                product=item.product,
                channel=item.channel,
                image_src=item.image_src,
                image_alt=item.image_alt,
            )
            for item in items
        ],
    )


async def update_copy(db: AsyncSession, payload: ReviewCopyUpdate) -> ReviewAdmin:
    row = await ensure_reviews(db)
    row.kicker = payload.kicker
    row.title = payload.title
    row.subtitle = payload.subtitle
    await db.commit()
    return await admin_view(db)


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> HomeReviewItem:
    item = await db.get(HomeReviewItem, item_id)
    if item is None:
        raise NotFoundError("Review not found")
    return item


async def _take_image(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    return store_image(await read_image(upload), folder=_MEDIA)


def _drop_image(stored: str | None) -> None:
    if stored:
        delete_owned_media({stored}, folder=_MEDIA)


async def create_item(
    db: AsyncSession, payload: ReviewItemWrite, image: UploadFile | None = None
) -> ReviewItemRead:
    stored = await _take_image(image)
    try:
        if stored is not None:
            payload = payload.model_copy(update={"image_src": stored})
        _reject_staged_path(payload.image_src)
        row = await ensure_reviews(db)
        count = await db.scalar(
            select(func.count())
            .select_from(HomeReviewItem)
            .where(HomeReviewItem.review_id == row.id)
        )
        if int(count or 0) >= MAX_ITEMS:
            raise UnprocessableError("You can show up to 24 reviews")
        current = await db.scalar(
            select(func.max(HomeReviewItem.sort_order)).where(HomeReviewItem.review_id == row.id)
        )
        item = HomeReviewItem(
            review_id=row.id,
            sort_order=0 if current is None else int(current) + 1,
            **payload.model_dump(),
        )
        db.add(item)
        await db.commit()
    except Exception:
        _drop_image(stored)
        raise
    await db.refresh(item)
    return present(item)


async def update_item(
    db: AsyncSession,
    item: HomeReviewItem,
    payload: ReviewItemUpdate,
    image: UploadFile | None = None,
) -> ReviewItemRead:
    stored = await _take_image(image)
    previous = owned_refs(item.image_src, folder=_MEDIA)
    try:
        if stored is not None:
            payload = payload.model_copy(update={"image_src": stored})
        _reject_staged_path(payload.image_src)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        await db.commit()
    except Exception:
        _drop_image(stored)
        raise
    await db.refresh(item)
    if stored is not None:
        replaced = previous - owned_refs(item.image_src, folder=_MEDIA)
        delete_owned_media(replaced, folder=_MEDIA)
    return present(item)


async def delete_item(db: AsyncSession, item: HomeReviewItem) -> None:
    owned = owned_refs(item.image_src, folder=_MEDIA)
    await db.delete(item)
    await db.commit()
    delete_owned_media(owned, folder=_MEDIA)


async def reorder(db: AsyncSession, payload: ReviewReorder) -> ReviewAdmin:
    row = await ensure_reviews(db)
    items = await _items(db, row.id, active_only=False)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every review in the new order")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return await admin_view(db)
