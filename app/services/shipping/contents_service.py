from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shipping.contents import ShippingContents
from app.schemas.shipping.contents import ContentsAdmin, ContentsPublic, ContentsWrite

SECTION_SLUG = "shipping"
EMPTY = ContentsPublic(title="", subtitle="", nav_label="")


def present(row: ShippingContents) -> ContentsAdmin:
    return ContentsAdmin(
        is_active=row.is_active,
        title=row.title,
        subtitle=row.subtitle,
        nav_label=row.nav_label,
    )


def present_public(row: ShippingContents) -> ContentsPublic:
    if not row.is_active:
        return EMPTY
    return ContentsPublic(title=row.title, subtitle=row.subtitle, nav_label=row.nav_label)


async def ensure_contents(db: AsyncSession) -> ShippingContents:
    row = await db.scalar(select(ShippingContents).where(ShippingContents.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ShippingContents(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> ContentsAdmin:
    return present(await ensure_contents(db))


async def public_view(db: AsyncSession) -> ContentsPublic:
    return present_public(await ensure_contents(db))


async def update_contents(db: AsyncSession, payload: ContentsWrite) -> ContentsAdmin:
    row = await ensure_contents(db)
    row.is_active = payload.is_active
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.nav_label = payload.nav_label
    await db.commit()
    await db.refresh(row)
    return present(row)
