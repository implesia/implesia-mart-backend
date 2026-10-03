import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.sustainability.quality import (
    SustainabilityQuality,
    SustainabilityQualityBadge,
    SustainabilityQualityStep,
)
from app.schemas.sustainability.quality import (
    QualityAdmin,
    QualityBadgePublic,
    QualityBadgeRead,
    QualityImageRead,
    QualityPublic,
    QualityStepPublic,
    QualityStepRead,
    QualityWrite,
)
from app.services.image_storage import delete_owned_media, owned_refs, read_image, store_image

SECTION_SLUG = "sustainability"
_MEDIA = "sustainability"
MAX_STEPS = 12
MAX_BADGES = 12
DEFAULT_TITLE = "কোয়ালিটি নিশ্চয়তা প্রক্রিয়া"
DEFAULT_BODY = (
    "প্রোডাক্ট আপনার কাছে পৌঁছানোর আগে আমরা নিজে যাচাই করি — গ্যাজেট চালিয়ে টেস্ট, "
    "ড্রেসের সেলাই ও ফেব্রিক আলাদা করে চেক। যা অর্ডার করছেন, তা-ই হাতে পাবেন।"
)
DEFAULT_IMAGE_SRC = "/images/products/lamp/lamp-3.jpg"
DEFAULT_IMAGE_ALT = "সানসেট ল্যাম্প — কোয়ালিটি টেস্টেড প্রোডাক্ট"
DEFAULT_STEPS = (
    "গ্যাজেট চালিয়ে ও ড্রেসের ফিনিশিং দেখে পরীক্ষা",
    "নিরাপদে প্যাক করে পাঠানো",
    "হাতে পেয়ে দেখে তারপর পেমেন্ট (COD)",
)
DEFAULT_BADGES: tuple[tuple[str, str], ...] = (
    ("check_circle", "চেক করে পাঠাই"),
    ("payments", "ক্যাশ অন ডেলিভারি"),
)


def _image(row: SustainabilityQuality) -> QualityImageRead:
    return QualityImageRead(src=row.image_src, alt=row.image_alt)


def _public(
    row: SustainabilityQuality,
    steps: list[SustainabilityQualityStep],
    badges: list[SustainabilityQualityBadge],
) -> QualityPublic:
    return QualityPublic(
        title=row.title,
        body=row.body,
        image=_image(row),
        steps=[QualityStepPublic(id=step.id, text=step.text) for step in steps if step.is_active],
        badges=[
            QualityBadgePublic(id=badge.id, icon=badge.icon, label=badge.label)
            for badge in badges
            if badge.is_active
        ],
    )


def _admin(
    row: SustainabilityQuality,
    steps: list[SustainabilityQualityStep],
    badges: list[SustainabilityQualityBadge],
) -> QualityAdmin:
    return QualityAdmin(
        title=row.title,
        body=row.body,
        image=_image(row),
        steps=[
            QualityStepRead(id=step.id, text=step.text, is_active=step.is_active) for step in steps
        ],
        badges=[
            QualityBadgeRead(
                id=badge.id, icon=badge.icon, label=badge.label, is_active=badge.is_active
            )
            for badge in badges
        ],
    )


async def _steps(db: AsyncSession, quality_id: uuid.UUID) -> list[SustainabilityQualityStep]:
    result = await db.execute(
        select(SustainabilityQualityStep)
        .where(SustainabilityQualityStep.quality_id == quality_id)
        .order_by(SustainabilityQualityStep.sort_order, SustainabilityQualityStep.created_at)
    )
    return list(result.scalars().all())


async def _badges(db: AsyncSession, quality_id: uuid.UUID) -> list[SustainabilityQualityBadge]:
    result = await db.execute(
        select(SustainabilityQualityBadge)
        .where(SustainabilityQualityBadge.quality_id == quality_id)
        .order_by(SustainabilityQualityBadge.sort_order, SustainabilityQualityBadge.created_at)
    )
    return list(result.scalars().all())


async def ensure_quality(db: AsyncSession) -> SustainabilityQuality:
    row = await db.scalar(
        select(SustainabilityQuality).where(SustainabilityQuality.slug == SECTION_SLUG)
    )
    if row is not None:
        return row
    row = SustainabilityQuality(
        slug=SECTION_SLUG,
        title=DEFAULT_TITLE,
        body=DEFAULT_BODY,
        image_src=DEFAULT_IMAGE_SRC,
        image_alt=DEFAULT_IMAGE_ALT,
    )
    db.add(row)
    await db.flush()
    for index, text in enumerate(DEFAULT_STEPS):
        db.add(
            SustainabilityQualityStep(
                quality_id=row.id, text=text, is_active=True, sort_order=index
            )
        )
    for index, (icon, label) in enumerate(DEFAULT_BADGES):
        db.add(
            SustainabilityQualityBadge(
                quality_id=row.id, icon=icon, label=label, is_active=True, sort_order=index
            )
        )
    await db.commit()
    await db.refresh(row)
    return row


async def public_view(db: AsyncSession) -> QualityPublic:
    row = await ensure_quality(db)
    return _public(row, await _steps(db, row.id), await _badges(db, row.id))


async def admin_view(db: AsyncSession) -> QualityAdmin:
    row = await ensure_quality(db)
    return _admin(row, await _steps(db, row.id), await _badges(db, row.id))


def _check(payload: QualityWrite) -> None:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if len(payload.steps) > MAX_STEPS:
        raise UnprocessableError("You can add up to 12 steps")
    if len(payload.badges) > MAX_BADGES:
        raise UnprocessableError("You can add up to 12 badges")
    if any(not step.text for step in payload.steps):
        raise UnprocessableError("Write each step, or remove the empty one.")
    if any(not badge.label for badge in payload.badges):
        raise UnprocessableError("Write each badge, or remove the empty one.")


def _reject_staged_path(src: str) -> None:
    if src.startswith("/uploads/") or src.startswith("blob:"):
        raise UnprocessableError("Send the image file with the quality")


async def _take_image(upload: UploadFile | None) -> str | None:
    if upload is None or not upload.filename:
        return None
    return store_image(await read_image(upload), folder=_MEDIA)


async def update_quality(
    db: AsyncSession, payload: QualityWrite, upload: UploadFile | None
) -> QualityAdmin:
    _check(payload)
    row = await ensure_quality(db)
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
        existing_steps = await _steps(db, row.id)
        for index, step in enumerate(payload.steps):
            if index < len(existing_steps):
                existing_steps[index].text = step.text
                existing_steps[index].is_active = step.is_active
                existing_steps[index].sort_order = index
            else:
                db.add(
                    SustainabilityQualityStep(
                        quality_id=row.id,
                        text=step.text,
                        is_active=step.is_active,
                        sort_order=index,
                    )
                )
        for extra in existing_steps[len(payload.steps) :]:
            await db.delete(extra)
        existing_badges = await _badges(db, row.id)
        for index, badge in enumerate(payload.badges):
            if index < len(existing_badges):
                existing_badges[index].icon = badge.icon
                existing_badges[index].label = badge.label
                existing_badges[index].is_active = badge.is_active
                existing_badges[index].sort_order = index
            else:
                db.add(
                    SustainabilityQualityBadge(
                        quality_id=row.id,
                        icon=badge.icon,
                        label=badge.label,
                        is_active=badge.is_active,
                        sort_order=index,
                    )
                )
        for extra in existing_badges[len(payload.badges) :]:
            await db.delete(extra)
        await db.commit()
    except Exception:
        delete_owned_media(set(stored), folder=_MEDIA)
        raise
    await db.refresh(row)
    delete_owned_media(previous - owned_refs(row.image_src, folder=_MEDIA), folder=_MEDIA)
    return _admin(row, await _steps(db, row.id), await _badges(db, row.id))
