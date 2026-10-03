from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.sustainability.cta import SustainabilityCta
from app.schemas.sustainability.cta import CtaLink, CtaRead, CtaWrite

SECTION_SLUG = "sustainability"
DEFAULT_TITLE = "কোয়ালিটি চেক করা গ্যাজেট ও গর্জিয়াস ড্রেস"
DEFAULT_SUBTITLE = "হাতে পেয়ে দেখে তারপর ক্যাশ অন ডেলিভারি — সারাদেশে।"
DEFAULT_PRIMARY_LABEL = "সব প্রোডাক্ট"
DEFAULT_PRIMARY_HREF = "/products"
DEFAULT_SECONDARY_LABEL = "যোগাযোগ"
DEFAULT_SECONDARY_HREF = "/contact-us"


def present(row: SustainabilityCta) -> CtaRead:
    return CtaRead(
        title=row.title,
        subtitle=row.subtitle,
        primary_cta=CtaLink(label=row.primary_label, href=row.primary_href),
        secondary_cta=CtaLink(label=row.secondary_label, href=row.secondary_href),
    )


async def ensure_cta(db: AsyncSession) -> SustainabilityCta:
    row = await db.scalar(select(SustainabilityCta).where(SustainabilityCta.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = SustainabilityCta(
        slug=SECTION_SLUG,
        title=DEFAULT_TITLE,
        subtitle=DEFAULT_SUBTITLE,
        primary_label=DEFAULT_PRIMARY_LABEL,
        primary_href=DEFAULT_PRIMARY_HREF,
        secondary_label=DEFAULT_SECONDARY_LABEL,
        secondary_href=DEFAULT_SECONDARY_HREF,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> CtaRead:
    return present(await ensure_cta(db))


async def public_view(db: AsyncSession) -> CtaRead:
    return present(await ensure_cta(db))


async def update_cta(db: AsyncSession, payload: CtaWrite) -> CtaRead:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    row = await ensure_cta(db)
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.primary_label = payload.primary_cta.label
    row.primary_href = payload.primary_cta.href
    row.secondary_label = payload.secondary_cta.label
    row.secondary_href = payload.secondary_cta.href
    await db.commit()
    await db.refresh(row)
    return present(row)
