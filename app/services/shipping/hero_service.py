from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.shipping.hero import ShippingHero
from app.schemas.shipping.hero import HeroAdmin, HeroPublic, HeroWrite

SECTION_SLUG = "shipping"
EMPTY = HeroPublic(eyebrow="", title="", subtitle="")


def present(row: ShippingHero) -> HeroAdmin:
    return HeroAdmin(
        is_active=row.is_active,
        eyebrow=row.eyebrow,
        title=row.title,
        subtitle=row.subtitle,
    )


def present_public(row: ShippingHero) -> HeroPublic:
    if not row.is_active or not row.title:
        return EMPTY
    return HeroPublic(eyebrow=row.eyebrow, title=row.title, subtitle=row.subtitle)


async def ensure_hero(db: AsyncSession) -> ShippingHero:
    row = await db.scalar(select(ShippingHero).where(ShippingHero.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ShippingHero(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> HeroAdmin:
    return present(await ensure_hero(db))


async def public_view(db: AsyncSession) -> HeroPublic:
    return present_public(await ensure_hero(db))


async def update_hero(db: AsyncSession, payload: HeroWrite) -> HeroAdmin:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    row = await ensure_hero(db)
    row.is_active = payload.is_active
    row.eyebrow = payload.eyebrow
    row.title = payload.title
    row.subtitle = payload.subtitle
    await db.commit()
    await db.refresh(row)
    return present(row)
