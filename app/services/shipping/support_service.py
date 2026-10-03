from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.shipping.support import ShippingSupport
from app.schemas.shipping.support import SupportAdmin, SupportPublic, SupportWrite
from app.services.contact.hero_service import _safe_href

SECTION_SLUG = "support"
EMPTY = SupportPublic(
    icon="",
    nav_label="",
    title="",
    subtitle="",
    email="",
    phone="",
    primary_label="",
    primary_href="",
    secondary_label="",
    secondary_href="",
)


def _admin(row: ShippingSupport) -> SupportAdmin:
    return SupportAdmin(
        is_active=row.is_active,
        icon=row.icon,
        nav_label=row.nav_label,
        title=row.title,
        subtitle=row.subtitle,
        email=row.email,
        phone=row.phone,
        primary_label=row.primary_label,
        primary_href=row.primary_href,
        secondary_label=row.secondary_label,
        secondary_href=row.secondary_href,
    )


def _public(row: ShippingSupport) -> SupportPublic:
    if not row.is_active or not row.title:
        return EMPTY
    return SupportPublic(
        icon=row.icon,
        nav_label=row.nav_label,
        title=row.title,
        subtitle=row.subtitle,
        email=row.email,
        phone=row.phone,
        primary_label=row.primary_label,
        primary_href=row.primary_href,
        secondary_label=row.secondary_label,
        secondary_href=row.secondary_href,
    )


async def ensure_support(db: AsyncSession) -> ShippingSupport:
    row = await db.scalar(select(ShippingSupport).where(ShippingSupport.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ShippingSupport(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> SupportAdmin:
    return _admin(await ensure_support(db))


async def public_view(db: AsyncSession) -> SupportPublic:
    return _public(await ensure_support(db))


async def update_support(db: AsyncSession, payload: SupportWrite) -> SupportAdmin:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    _safe_href(payload.primary_href)
    _safe_href(payload.secondary_href)
    row = await ensure_support(db)
    row.is_active = payload.is_active
    row.icon = payload.icon
    row.nav_label = payload.nav_label
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
    return _admin(row)
