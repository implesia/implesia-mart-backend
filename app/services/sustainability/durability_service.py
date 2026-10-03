import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.sustainability.durability import (
    SustainabilityDurability,
    SustainabilityDurabilityBullet,
)
from app.schemas.sustainability.durability import (
    DurabilityAdmin,
    DurabilityBulletPublic,
    DurabilityBulletRead,
    DurabilityImageRead,
    DurabilityPublic,
    DurabilityWrite,
)
from app.services.image_storage import delete_owned_media, owned_refs, read_image, store_image

SECTION_SLUG = "sustainability"
_MEDIA = "sustainability"
MAX_BULLETS = 12
DEFAULT_TITLE = "দীর্ঘস্থায়ী প্রোডাক্ট, কম বর্জ্য"
DEFAULT_BODY = (
    "শুধু ট্রেন্ডিং নয় — যেগুলো দীর্ঘদিন কাজে লাগে। ভালো গ্যাজেট মানে কম রিপ্লেসমেন্ট; "
    "হাতে তৈরি গর্জিয়াস ড্রেস মানে ফাস্ট ফ্যাশনের চেয়ে কম কাপড়-বর্জ্য।"
)
DEFAULT_IMAGE_SRC = "/images/products/baby-products/3-quater-ground-frog.jpeg"
DEFAULT_IMAGE_ALT = "হাতে তৈরি গর্জিয়াস ড্রেস — টেকসই ফেব্রিক ও সেলাই"
DEFAULT_BULLETS = (
    "মানসম্পন্ন ম্যাটেরিয়াল ও বিল্ড",
    "হাতে তৈরি ড্রেসে টেকসই ফেব্রিক ও সেলাই",
    "কম রিপ্লেসমেন্ট, কম ই-বর্জ্য",
    "হাতে পেয়ে দেখে তারপর পেমেন্ট",
)


def _image(row: SustainabilityDurability) -> DurabilityImageRead:
    return DurabilityImageRead(src=row.image_src, alt=row.image_alt)


def _public(
    row: SustainabilityDurability, bullets: list[SustainabilityDurabilityBullet]
) -> DurabilityPublic:
    return DurabilityPublic(
        title=row.title,
        body=row.body,
        image=_image(row),
        bullets=[
            DurabilityBulletPublic(id=bullet.id, text=bullet.text)
            for bullet in bullets
            if bullet.is_active
        ],
    )


def _admin(
    row: SustainabilityDurability, bullets: list[SustainabilityDurabilityBullet]
) -> DurabilityAdmin:
    return DurabilityAdmin(
        title=row.title,
        body=row.body,
        image=_image(row),
        bullets=[
            DurabilityBulletRead(id=bullet.id, text=bullet.text, is_active=bullet.is_active)
            for bullet in bullets
        ],
    )


async def _bullets(
    db: AsyncSession, durability_id: uuid.UUID
) -> list[SustainabilityDurabilityBullet]:
    result = await db.execute(
        select(SustainabilityDurabilityBullet)
        .where(SustainabilityDurabilityBullet.durability_id == durability_id)
        .order_by(
            SustainabilityDurabilityBullet.sort_order,
            SustainabilityDurabilityBullet.created_at,
        )
    )
    return list(result.scalars().all())


async def ensure_durability(db: AsyncSession) -> SustainabilityDurability:
    row = await db.scalar(
        select(SustainabilityDurability).where(SustainabilityDurability.slug == SECTION_SLUG)
    )
    if row is not None:
        return row
    row = SustainabilityDurability(
        slug=SECTION_SLUG,
        title=DEFAULT_TITLE,
        body=DEFAULT_BODY,
        image_src=DEFAULT_IMAGE_SRC,
        image_alt=DEFAULT_IMAGE_ALT,
    )
    db.add(row)
    await db.flush()
    for index, text in enumerate(DEFAULT_BULLETS):
        db.add(
            SustainabilityDurabilityBullet(
                durability_id=row.id, text=text, is_active=True, sort_order=index
            )
        )
    await db.commit()
    await db.refresh(row)
    return row


async def public_view(db: AsyncSession) -> DurabilityPublic:
    row = await ensure_durability(db)
    return _public(row, await _bullets(db, row.id))


async def admin_view(db: AsyncSession) -> DurabilityAdmin:
    row = await ensure_durability(db)
    return _admin(row, await _bullets(db, row.id))


def _check(payload: DurabilityWrite) -> None:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if len(payload.bullets) > MAX_BULLETS:
        raise UnprocessableError("You can add up to 12 points")
    if any(not bullet.text for bullet in payload.bullets):
        raise UnprocessableError("Write each point, or remove the empty one.")


def _reject_staged_path(src: str) -> None:
    if src.startswith("/uploads/") or src.startswith("blob:"):
        raise UnprocessableError("Send the image file with the durability")


async def _take_image(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    return store_image(await read_image(upload), folder=_MEDIA)


async def update_durability(
    db: AsyncSession, payload: DurabilityWrite, upload: UploadFile | None
) -> DurabilityAdmin:
    _check(payload)
    row = await ensure_durability(db)
    stored: list[str] = []
    try:
        taken = await _take_image(upload)
        if taken is not None:
            stored.append(taken)
            src = taken
        else:
            src = payload.image.src
            if not src:
                raise UnprocessableError("Cover photo is required.")
            _reject_staged_path(src)
        previous = owned_refs(row.image_src, folder=_MEDIA)
        row.title = payload.title
        row.body = payload.body
        row.image_src = src
        row.image_alt = payload.image.alt
        existing = await _bullets(db, row.id)
        for index, bullet in enumerate(payload.bullets):
            if index < len(existing):
                existing[index].text = bullet.text
                existing[index].is_active = bullet.is_active
                existing[index].sort_order = index
            else:
                db.add(
                    SustainabilityDurabilityBullet(
                        durability_id=row.id,
                        text=bullet.text,
                        is_active=bullet.is_active,
                        sort_order=index,
                    )
                )
        for extra in existing[len(payload.bullets) :]:
            await db.delete(extra)
        await db.commit()
    except Exception:
        delete_owned_media(set(stored), folder=_MEDIA)
        raise
    await db.refresh(row)
    delete_owned_media(previous - owned_refs(row.image_src, folder=_MEDIA), folder=_MEDIA)
    return _admin(row, await _bullets(db, row.id))
