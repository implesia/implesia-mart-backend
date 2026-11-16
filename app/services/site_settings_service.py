from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_settings import SiteSettings
from app.schemas.site_settings import SiteSettingsRead, SiteSettingsUpdate

SETTINGS_SLUG = "main"


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _read(row: SiteSettings | None) -> SiteSettingsRead:
    if row is None:
        return SiteSettingsRead()
    return SiteSettingsRead(
        seo_title=_blank(row.seo_title),
        seo_description=_blank(row.seo_description),
        seo_title_template=_blank(row.seo_title_template),
    )


async def _row(db: AsyncSession) -> SiteSettings | None:
    return await db.scalar(select(SiteSettings).where(SiteSettings.slug == SETTINGS_SLUG))


async def public_view(db: AsyncSession) -> SiteSettingsRead:
    return _read(await _row(db))


async def admin_view(db: AsyncSession) -> SiteSettingsRead:
    return await public_view(db)


async def update(db: AsyncSession, payload: SiteSettingsUpdate) -> SiteSettingsRead:
    row = await _row(db)
    if row is None:
        row = SiteSettings(slug=SETTINGS_SLUG)
        db.add(row)
    sent = payload.model_fields_set
    if "seo_title" in sent:
        row.seo_title = payload.seo_title
    if "seo_description" in sent:
        row.seo_description = payload.seo_description
    if "seo_title_template" in sent:
        row.seo_title_template = payload.seo_title_template
    await db.commit()
    await db.refresh(row)
    return _read(row)
