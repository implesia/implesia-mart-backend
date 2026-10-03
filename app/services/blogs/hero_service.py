from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.blogs.hero import BlogHero
from app.schemas.blogs.hero import HeroAdmin, HeroPublic, HeroWrite

SECTION_SLUG = "blogs"
EMPTY = HeroPublic(eyebrow="", title="", subtitle="", count_label="")


def present(row: BlogHero) -> HeroAdmin:
    return HeroAdmin(
        is_active=row.is_active,
        eyebrow=row.eyebrow,
        title=row.title,
        subtitle=row.subtitle,
        count_label=row.count_label,
    )


def present_public(row: BlogHero) -> HeroPublic:
    if not row.is_active or not row.title:
        return EMPTY
    shown = present(row)
    return HeroPublic(
        eyebrow=shown.eyebrow,
        title=shown.title,
        subtitle=shown.subtitle,
        count_label=shown.count_label,
    )


async def ensure_hero(db: AsyncSession) -> BlogHero:
    row = await db.scalar(select(BlogHero).where(BlogHero.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = BlogHero(slug=SECTION_SLUG, is_active=True)
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
    row.count_label = payload.count_label
    await db.commit()
    await db.refresh(row)
    return present(row)
