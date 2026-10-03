from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.privacy.hero import PrivacyHero
from app.schemas.privacy.hero import HeroAdmin, HeroPublic, HeroWrite

SECTION_SLUG = "privacy"
EMPTY = HeroPublic(eyebrow="", title="", subtitle="", updated_label="", last_updated="")


def present(row: PrivacyHero) -> HeroAdmin:
    return HeroAdmin(
        is_active=row.is_active,
        eyebrow=row.eyebrow,
        title=row.title,
        subtitle=row.subtitle,
        updated_label=row.updated_label,
        last_updated=row.last_updated,
    )


def present_public(row: PrivacyHero) -> HeroPublic:
    if not row.is_active or not row.title:
        return EMPTY
    shown = present(row)
    return HeroPublic(
        eyebrow=shown.eyebrow,
        title=shown.title,
        subtitle=shown.subtitle,
        updated_label=shown.updated_label,
        last_updated=shown.last_updated,
    )


async def ensure_hero(db: AsyncSession) -> PrivacyHero:
    row = await db.scalar(select(PrivacyHero).where(PrivacyHero.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = PrivacyHero(slug=SECTION_SLUG, is_active=True)
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
    row.updated_label = payload.updated_label
    row.last_updated = payload.last_updated
    await db.commit()
    await db.refresh(row)
    return present(row)
