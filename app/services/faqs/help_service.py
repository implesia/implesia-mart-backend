from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.faqs.help import FaqHelp
from app.schemas.faqs.help import HelpAdmin, HelpPublic, HelpWrite
from app.services.contact.hero_service import _safe_href

SECTION_SLUG = "faqs"
EMPTY = HelpPublic(
    title="",
    subtitle="",
    email="",
    phone="",
    primary_label="",
    primary_href="",
    secondary_label="",
    secondary_href="",
)


def present(row: FaqHelp) -> HelpAdmin:
    return HelpAdmin(
        is_active=row.is_active,
        title=row.title,
        subtitle=row.subtitle,
        email=row.email,
        phone=row.phone,
        primary_label=row.primary_label,
        primary_href=row.primary_href,
        secondary_label=row.secondary_label,
        secondary_href=row.secondary_href,
    )


def present_public(row: FaqHelp) -> HelpPublic:
    if not row.is_active or not row.title:
        return EMPTY
    shown = present(row)
    return HelpPublic(
        title=shown.title,
        subtitle=shown.subtitle,
        email=shown.email,
        phone=shown.phone,
        primary_label=shown.primary_label,
        primary_href=shown.primary_href,
        secondary_label=shown.secondary_label,
        secondary_href=shown.secondary_href,
    )


async def ensure_help(db: AsyncSession) -> FaqHelp:
    row = await db.scalar(select(FaqHelp).where(FaqHelp.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = FaqHelp(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> HelpAdmin:
    return present(await ensure_help(db))


async def public_view(db: AsyncSession) -> HelpPublic:
    return present_public(await ensure_help(db))


async def update_help(db: AsyncSession, payload: HelpWrite) -> HelpAdmin:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    _safe_href(payload.primary_href)
    _safe_href(payload.secondary_href)
    row = await ensure_help(db)
    row.is_active = payload.is_active
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.email = payload.email
    row.phone = payload.phone
    row.primary_label = payload.primary_label
    row.primary_href = payload.primary_href
    row.secondary_label = payload.secondary_label
    row.secondary_href = payload.secondary_href
    await db.commit()
    await db.refresh(row)
    return present(row)
