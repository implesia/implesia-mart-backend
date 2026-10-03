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
from app.services.image_storage import delete_owned_media, owned_refs, read_image, store_image

SECTION_SLUG = "sustainability"
_MEDIA = "sustainability"
MAX_PHOTOS = 12
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
    {
        "src": "/images/products/baby-products/baby-frock-with-baby.jpeg",
        "alt": "হাতে তৈরি বেবি পার্টি ফ্রক",
        "sort_order": 1,
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
        images=[_public_image(image) for image in visible],
    )


def _admin(row: SustainabilityOrigin, images: list[SustainabilityOriginImage]) -> OriginAdmin:
    return OriginAdmin(
        eyebrow=row.eyebrow,
        title=row.title,
        body=row.body,
        quote=row.quote,
        images=[_admin_image(image) for image in images],
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


def _reject_staged_path(src: str) -> None:
    if src.startswith("/uploads/") or src.startswith("blob:"):
        raise UnprocessableError("Send the image file with the point of view")


async def _take_image(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    return store_image(await read_image(upload), folder=_MEDIA)


async def update_origin(
    db: AsyncSession, payload: OriginWrite, uploads: dict[int, UploadFile]
) -> OriginAdmin:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if len(payload.images) > MAX_PHOTOS:
        raise UnprocessableError("You can add up to 12 photos")
    row = await ensure_origin(db)
    stored: list[str] = []
    try:
        resolved: list[tuple[str, str, bool]] = []
        for index, image in enumerate(payload.images):
            taken = await _take_image(uploads.get(index))
            if taken is not None:
                stored.append(taken)
                src = taken
            else:
                src = image.src
                if not src:
                    raise UnprocessableError("Add an image, or remove the empty photo.")
                _reject_staged_path(src)
            resolved.append((src, image.alt, image.is_active))
        existing = await _images(db, row.id)
        previous = owned_refs(*(item.src for item in existing), folder=_MEDIA)
        for index, (src, alt, active) in enumerate(resolved):
            if index < len(existing):
                existing[index].src = src
                existing[index].alt = alt
                existing[index].is_active = active
                existing[index].sort_order = index
            else:
                db.add(
                    SustainabilityOriginImage(
                        origin_id=row.id,
                        src=src,
                        alt=alt,
                        is_active=active,
                        sort_order=index,
                    )
                )
        for extra in existing[len(resolved) :]:
            await db.delete(extra)
        row.eyebrow = payload.eyebrow
        row.title = payload.title
        row.body = payload.body
        row.quote = payload.quote
        await db.commit()
    except Exception:
        delete_owned_media(set(stored), folder=_MEDIA)
        raise
    await db.refresh(row)
    current = await _images(db, row.id)
    kept = owned_refs(*(item.src for item in current), folder=_MEDIA)
    delete_owned_media(previous - kept, folder=_MEDIA)
    return _admin(row, current)
