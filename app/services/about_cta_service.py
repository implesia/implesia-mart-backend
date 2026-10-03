from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.about_cta import AboutCta
from app.schemas.about_cta import CtaLink, CtaPublic, CtaRead, CtaWrite

SECTION_SLUG = "about"
DEFAULTS = {
    "title": "আজই খুঁজে নিন আপনার প্রয়োজনীয় প্রোডাক্ট",
    "subtitle": "গ্যাজেট হোক বা গর্জিয়াস ড্রেস — হাতে পেয়ে দেখে তারপর ক্যাশ অন ডেলিভারি।",
    "primary_label": "সব প্রোডাক্ট",
    "primary_href": "/products",
    "secondary_label": "যোগাযোগ",
    "secondary_href": "/contact-us",
}
EMPTY = CtaPublic(
    title="",
    subtitle="",
    primary_cta=CtaLink(label="", href=""),
    secondary_cta=CtaLink(label="", href=""),
)


def present(row: AboutCta) -> CtaRead:
    return CtaRead(
        is_active=row.is_active,
        title=row.title,
        subtitle=row.subtitle,
        primary_cta=CtaLink(label=row.primary_label, href=row.primary_href),
        secondary_cta=CtaLink(label=row.secondary_label, href=row.secondary_href),
    )


def present_public(row: AboutCta) -> CtaPublic:
    if not row.is_active:
        return EMPTY
    return CtaPublic(
        title=row.title,
        subtitle=row.subtitle,
        primary_cta=CtaLink(label=row.primary_label, href=row.primary_href),
        secondary_cta=CtaLink(label=row.secondary_label, href=row.secondary_href),
    )


async def ensure_cta(db: AsyncSession) -> AboutCta:
    row = await db.scalar(select(AboutCta).where(AboutCta.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = AboutCta(slug=SECTION_SLUG, is_active=True, **DEFAULTS)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> CtaRead:
    return present(await ensure_cta(db))


async def public_view(db: AsyncSession) -> CtaPublic:
    return present_public(await ensure_cta(db))


async def update_cta(db: AsyncSession, payload: CtaWrite) -> CtaRead:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    row = await ensure_cta(db)
    row.is_active = payload.is_active
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.primary_label = payload.primary_cta.label
    row.primary_href = payload.primary_cta.href
    row.secondary_label = payload.secondary_cta.label
    row.secondary_href = payload.secondary_cta.href
    await db.commit()
    await db.refresh(row)
    return present(row)
