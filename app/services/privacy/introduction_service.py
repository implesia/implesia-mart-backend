import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.privacy.introduction import PrivacyIntroduction, PrivacyIntroductionParagraph
from app.schemas.privacy.introduction import (
    IntroductionAdmin,
    IntroductionPublic,
    IntroductionWrite,
    ParagraphPublic,
    ParagraphRead,
    ParagraphWrite,
)

SECTION_SLUG = "introduction"
MAX_PARAGRAPHS = 12
EMPTY = IntroductionPublic(icon="", nav_label="", heading="", paragraphs=[])


def _admin(
    row: PrivacyIntroduction, items: list[PrivacyIntroductionParagraph]
) -> IntroductionAdmin:
    return IntroductionAdmin(
        is_active=row.is_active,
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        paragraphs=[
            ParagraphRead(id=str(item.id), text=item.text, is_active=item.is_active)
            for item in items
        ],
    )


def _public(
    row: PrivacyIntroduction, items: list[PrivacyIntroductionParagraph]
) -> IntroductionPublic:
    if not row.is_active or not row.heading:
        return EMPTY
    return IntroductionPublic(
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        paragraphs=[
            ParagraphPublic(id=str(item.id), text=item.text)
            for item in items
            if item.is_active and item.text
        ],
    )


async def _paragraphs(db: AsyncSession, intro_id: uuid.UUID) -> list[PrivacyIntroductionParagraph]:
    rows = await db.scalars(
        select(PrivacyIntroductionParagraph)
        .where(PrivacyIntroductionParagraph.intro_id == intro_id)
        .order_by(PrivacyIntroductionParagraph.sort_order, PrivacyIntroductionParagraph.created_at)
    )
    return list(rows)


async def ensure_introduction(db: AsyncSession) -> PrivacyIntroduction:
    row = await db.scalar(
        select(PrivacyIntroduction).where(PrivacyIntroduction.slug == SECTION_SLUG)
    )
    if row is not None:
        return row
    row = PrivacyIntroduction(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> IntroductionAdmin:
    row = await ensure_introduction(db)
    return _admin(row, await _paragraphs(db, row.id))


async def public_view(db: AsyncSession) -> IntroductionPublic:
    row = await ensure_introduction(db)
    return _public(row, await _paragraphs(db, row.id))


def _check(payload: IntroductionWrite) -> None:
    if not payload.heading:
        raise UnprocessableError("Heading is required.")
    if len(payload.paragraphs) > MAX_PARAGRAPHS:
        raise UnprocessableError("You can add up to 12 paragraphs.")
    if any(not item.text for item in payload.paragraphs):
        raise UnprocessableError("Every paragraph needs text, or remove the empty ones.")


def _match(
    raw: str | None,
    existing: dict[uuid.UUID, PrivacyIntroductionParagraph],
) -> PrivacyIntroductionParagraph | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _apply(
    db: AsyncSession,
    intro_id: uuid.UUID,
    items: list[ParagraphWrite],
    existing: dict[uuid.UUID, PrivacyIntroductionParagraph],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                PrivacyIntroductionParagraph(
                    intro_id=intro_id,
                    text=item.text,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.text = item.text
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


async def update_introduction(db: AsyncSession, payload: IntroductionWrite) -> IntroductionAdmin:
    _check(payload)
    row = await ensure_introduction(db)
    row.is_active = payload.is_active
    row.icon = payload.icon
    row.nav_label = payload.nav_label
    row.heading = payload.heading
    stored = {item.id: item for item in await _paragraphs(db, row.id)}
    _apply(db, row.id, payload.paragraphs, stored)
    for extra in stored.values():
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _paragraphs(db, row.id))
