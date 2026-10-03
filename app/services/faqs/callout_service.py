from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.faqs.callout import FaqCallout
from app.schemas.faqs.callout import CalloutAdmin, CalloutPublic, CalloutWrite

SECTION_SLUG = "faqs"
EMPTY = CalloutPublic(eyebrow="", body="")


def present(row: FaqCallout) -> CalloutAdmin:
    return CalloutAdmin(is_active=row.is_active, eyebrow=row.eyebrow, body=row.body)


def present_public(row: FaqCallout) -> CalloutPublic:
    if not row.is_active or not row.body:
        return EMPTY
    return CalloutPublic(eyebrow=row.eyebrow, body=row.body)


async def ensure_callout(db: AsyncSession) -> FaqCallout:
    row = await db.scalar(select(FaqCallout).where(FaqCallout.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = FaqCallout(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> CalloutAdmin:
    return present(await ensure_callout(db))


async def public_view(db: AsyncSession) -> CalloutPublic:
    return present_public(await ensure_callout(db))


async def update_callout(db: AsyncSession, payload: CalloutWrite) -> CalloutAdmin:
    if not payload.body:
        raise UnprocessableError("Note is required.")
    row = await ensure_callout(db)
    row.is_active = payload.is_active
    row.eyebrow = payload.eyebrow
    row.body = payload.body
    await db.commit()
    await db.refresh(row)
    return present(row)
