import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.about_hero import AboutHero, AboutHeroImage
from app.schemas.about_hero import (
    AboutHeroAdmin,
    AboutHeroImageAdmin,
    AboutHeroImagePublic,
    AboutHeroPublic,
    AboutHeroWrite,
)
from app.services.image_storage import delete_owned_media, owned_refs, read_image, store_image

HERO_SLUG = "about"
_MEDIA = "about"
DEFAULT_EYEBROW = "আমাদের সম্পর্কে"
DEFAULT_TITLE = "আপনার নিশ্চিন্ত অনলাইন শপিং পার্টনার।"
DEFAULT_SUBTITLE = (
    "ঘরে বসে কোয়ালিটি চেক করা প্রোডাক্ট — ক্যাশ অন ডেলিভারিতে, কোনো আগাম ঝুঁকি ছাড়াই। "
    "ট্রেন্ডিং গ্যাজেট আর হাতে তৈরি গর্জিয়াস ড্রেস, একই বিশ্বাসে।"
)
DEFAULT_PRIMARY_LABEL = "সব প্রোডাক্ট"
DEFAULT_PRIMARY_HREF = "/products"
DEFAULT_SECONDARY_LABEL = "যোগাযোগ"
DEFAULT_SECONDARY_HREF = "/contact-us"
DEFAULT_IMAGES: tuple[dict[str, object], ...] = (
    {
        "src": "/images/products/lamp/lamp-1.jpg",
        "alt": "সানসেট ল্যাম্প — ইমপ্লেসিয়া মার্টের ট্রেন্ডিং গ্যাজেট",
        "sort_order": 0,
    },
    {
        "src": "/images/products/baby-products/female-gorgious-ground-dress.jpeg",
        "alt": "হাতে তৈরি গর্জিয়াস উইমেন্স গাউন",
        "sort_order": 1,
    },
)


def _public_image(image: AboutHeroImage) -> AboutHeroImagePublic:
    return AboutHeroImagePublic(id=image.id, src=image.src, alt=image.alt)


def _admin_image(image: AboutHeroImage) -> AboutHeroImageAdmin:
    return AboutHeroImageAdmin(
        id=image.id, src=image.src, alt=image.alt, sort_order=image.sort_order
    )


def _public(row: AboutHero, images: list[AboutHeroImage]) -> AboutHeroPublic:
    return AboutHeroPublic(
        eyebrow=row.eyebrow,
        title=row.title,
        subtitle=row.subtitle,
        primary_label=row.primary_label,
        primary_href=row.primary_href,
        secondary_label=row.secondary_label,
        secondary_href=row.secondary_href,
        images=[_public_image(image) for image in images],
    )


def _admin(row: AboutHero, images: list[AboutHeroImage]) -> AboutHeroAdmin:
    return AboutHeroAdmin(
        eyebrow=row.eyebrow,
        title=row.title,
        subtitle=row.subtitle,
        primary_label=row.primary_label,
        primary_href=row.primary_href,
        secondary_label=row.secondary_label,
        secondary_href=row.secondary_href,
        images=[_admin_image(image) for image in images],
    )


async def _images(db: AsyncSession, hero_id: uuid.UUID) -> list[AboutHeroImage]:
    result = await db.execute(
        select(AboutHeroImage)
        .where(AboutHeroImage.hero_id == hero_id)
        .order_by(AboutHeroImage.sort_order, AboutHeroImage.created_at)
    )
    return list(result.scalars().all())


async def ensure_hero(db: AsyncSession) -> AboutHero:
    row = await db.scalar(select(AboutHero).where(AboutHero.slug == HERO_SLUG))
    if row is not None:
        return row
    row = AboutHero(
        slug=HERO_SLUG,
        eyebrow=DEFAULT_EYEBROW,
        title=DEFAULT_TITLE,
        subtitle=DEFAULT_SUBTITLE,
        primary_label=DEFAULT_PRIMARY_LABEL,
        primary_href=DEFAULT_PRIMARY_HREF,
        secondary_label=DEFAULT_SECONDARY_LABEL,
        secondary_href=DEFAULT_SECONDARY_HREF,
    )
    db.add(row)
    await db.flush()
    for raw in DEFAULT_IMAGES:
        db.add(AboutHeroImage(hero_id=row.id, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def public_view(db: AsyncSession) -> AboutHeroPublic:
    row = await ensure_hero(db)
    return _public(row, await _images(db, row.id))


async def admin_view(db: AsyncSession) -> AboutHeroAdmin:
    row = await ensure_hero(db)
    return _admin(row, await _images(db, row.id))


def _reject_staged_path(src: str) -> None:
    if src.startswith("/uploads/") or src.startswith("blob:"):
        raise UnprocessableError("Send the image file with the hero")


async def _take_image(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    return store_image(await read_image(upload), folder=_MEDIA)


async def update_hero(
    db: AsyncSession,
    payload: AboutHeroWrite,
    image_0: UploadFile | None = None,
    image_1: UploadFile | None = None,
) -> AboutHeroAdmin:
    row = await ensure_hero(db)
    uploads = (image_0, image_1)
    stored: list[str] = []
    try:
        resolved: list[tuple[str, str]] = []
        for index, image in enumerate(payload.images):
            taken = await _take_image(uploads[index] if index < len(uploads) else None)
            if taken is not None:
                stored.append(taken)
                src = taken
            else:
                src = image.src
                if not src:
                    raise UnprocessableError("Add an image, or remove the empty photo.")
                _reject_staged_path(src)
            resolved.append((src, image.alt))
        existing = await _images(db, row.id)
        previous = owned_refs(*(item.src for item in existing), folder=_MEDIA)
        for index, (src, alt) in enumerate(resolved):
            if index < len(existing):
                existing[index].src = src
                existing[index].alt = alt
                existing[index].sort_order = index
            else:
                db.add(AboutHeroImage(hero_id=row.id, src=src, alt=alt, sort_order=index))
        for extra in existing[len(resolved) :]:
            await db.delete(extra)
        row.eyebrow = payload.eyebrow
        row.title = payload.title
        row.subtitle = payload.subtitle
        row.primary_label = payload.primary_label
        row.primary_href = payload.primary_href
        row.secondary_label = payload.secondary_label
        row.secondary_href = payload.secondary_href
        await db.commit()
    except Exception:
        delete_owned_media(set(stored), folder=_MEDIA)
        raise
    await db.refresh(row)
    current = await _images(db, row.id)
    kept = owned_refs(*(item.src for item in current), folder=_MEDIA)
    delete_owned_media(previous - kept, folder=_MEDIA)
    return _admin(row, current)
