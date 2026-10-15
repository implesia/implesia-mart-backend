import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.sustainability.origin import SustainabilityOrigin, SustainabilityOriginImage
from app.schemas.sustainability.origin import (
    OriginAdmin,
    OriginImageAdmin,
    OriginImagePublic,
    OriginPublic,
    OriginWrite,
)
from app.services.image_storage import delete_owned_media, owned_refs
from app.services.sustainability.optional_image import resolve_optional_image

SECTION_SLUG = "sustainability"
_MEDIA = "sustainability"
DEFAULT_COPY = {
    "eyebrow": "আমাদের দৃষ্টিভঙ্গি",
    "title": "কোয়ালিটি এখন বিলাসিতা নয়, দায়িত্ব",
    "body": (
        "ইমপ্লেসিয়া মার্ট শুরু হয়েছিল একটা সহজ প্রশ্ন থেকে — কেন ভালো প্রোডাক্ট মানেই বেশি ঝুঁকি হবে? "
        "প্রতিটি গ্যাজেট অর্ডারের আগে নিজেরা টেস্ট করি, আর প্রতিটি ড্রেস হাতে বানিয়ে চেক করে পাঠাই — "
        "যাতে প্রথমবারেই সঠিক জিনিস হাতে পান। কম রিটার্ন, কম বর্জ্য।"
    ),
    "quote": "কোয়ালিটি একটি অভ্যাস, একবারের কাজ নয়।",
}
DEFAULT_IMAGES: tuple[dict[str, object], ...] = (
    {
        "src": "/images/products/lamp/lamp-2.jpg",
        "alt": "সানসেট ল্যাম্প — কোয়ালিটি চেক করা প্রোডাক্ট",
        "sort_order": 0,
    },
)


def _public_image(image: SustainabilityOriginImage) -> OriginImagePublic:
    return OriginImagePublic(id=image.id, src=image.src, alt=image.alt)


def _admin_image(image: SustainabilityOriginImage) -> OriginImageAdmin:
    return OriginImageAdmin(id=image.id, src=image.src, alt=image.alt, is_active=image.is_active)


def _public(row: SustainabilityOrigin, images: list[SustainabilityOriginImage]) -> OriginPublic:
    visible = [image for image in images if image.is_active]
    return OriginPublic(
        eyebrow=row.eyebrow,
        title=row.title,
        body=row.body,
        quote=row.quote,
        image=_public_image(visible[0]) if visible else None,
        images=[_public_image(image) for image in visible[:1]],
    )


def _admin(row: SustainabilityOrigin, images: list[SustainabilityOriginImage]) -> OriginAdmin:
    return OriginAdmin(
        eyebrow=row.eyebrow,
        title=row.title,
        body=row.body,
        quote=row.quote,
        image=_admin_image(images[0]) if images else None,
        images=[_admin_image(image) for image in images[:1]],
    )


async def _images(db: AsyncSession, origin_id: uuid.UUID) -> list[SustainabilityOriginImage]:
    result = await db.execute(
        select(SustainabilityOriginImage)
        .where(SustainabilityOriginImage.origin_id == origin_id)
        .order_by(SustainabilityOriginImage.sort_order, SustainabilityOriginImage.created_at)
    )
    return list(result.scalars().all())


async def ensure_origin(db: AsyncSession) -> SustainabilityOrigin:
    row = await db.scalar(
        select(SustainabilityOrigin).where(SustainabilityOrigin.slug == SECTION_SLUG)
    )
    if row is not None:
        return row
    row = SustainabilityOrigin(slug=SECTION_SLUG, **DEFAULT_COPY)
    db.add(row)
    await db.flush()
    for raw in DEFAULT_IMAGES:
        db.add(SustainabilityOriginImage(origin_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def public_view(db: AsyncSession) -> OriginPublic:
    row = await ensure_origin(db)
    return _public(row, await _images(db, row.id))


async def admin_view(db: AsyncSession) -> OriginAdmin:
    row = await ensure_origin(db)
    return _admin(row, await _images(db, row.id))


async def update_origin(
    db: AsyncSession, payload: OriginWrite, image: UploadFile | None = None
) -> OriginAdmin:
    """Save the point of view. The single photo is optional; with none the row is removed."""
    if not payload.title:
        raise UnprocessableError("Title is required.")
    row = await ensure_origin(db)
    src, alt, stored = await resolve_optional_image(
        payload.image, image, "Send the image file with the point of view"
    )
    try:
        existing = await _images(db, row.id)
        previous = owned_refs(*(item.src for item in existing), folder=_MEDIA)
        if src:
            if existing:
                existing[0].src = src
                existing[0].alt = alt
                existing[0].is_active = True
                existing[0].sort_order = 0
            else:
                db.add(
                    SustainabilityOriginImage(
                        origin_id=row.id, src=src, alt=alt, is_active=True, sort_order=0
                    )
                )
        for extra in existing[1:] if src else existing:
            await db.delete(extra)
        row.eyebrow = payload.eyebrow
        row.title = payload.title
        row.body = payload.body
        row.quote = payload.quote
        await db.commit()
    except Exception:
        if stored:
            delete_owned_media({stored}, folder=_MEDIA)
        raise
    await db.refresh(row)
    current = await _images(db, row.id)
    kept = owned_refs(*(item.src for item in current), folder=_MEDIA)
    delete_owned_media(previous - kept, folder=_MEDIA)
    return _admin(row, current)
