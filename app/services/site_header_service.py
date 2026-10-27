import copy

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_header import SiteHeader
from app.schemas.site_footer import FooterLink
from app.schemas.site_header import HeaderAdmin, HeaderPublic, HeaderWrite
from app.services.site_header_defaults import DEFAULT_ITEMS

HEADER_SLUG = "main"

_LINKS = TypeAdapter(list[FooterLink])


async def _row(db: AsyncSession) -> SiteHeader | None:
    return await db.scalar(select(SiteHeader).where(SiteHeader.slug == HEADER_SLUG))


def _defaults() -> HeaderAdmin:
    return HeaderAdmin(
        items=_LINKS.validate_python(copy.deepcopy(DEFAULT_ITEMS)),
        is_default=True,
    )


async def admin_view(db: AsyncSession) -> HeaderAdmin:
    row = await _row(db)
    if row is None:
        return _defaults()
    try:
        items = _LINKS.validate_python(row.items)
    except ValidationError:
        return _defaults()  # a bad stored row never breaks the storefront
    if not any(item.enabled for item in items):
        return _defaults()  # an empty menu would strand visitors
    return HeaderAdmin(items=items, is_default=False)


async def public_view(db: AsyncSession) -> HeaderPublic:
    admin = await admin_view(db)
    return HeaderPublic(items=[item for item in admin.items if item.enabled])


async def update(db: AsyncSession, payload: HeaderWrite) -> HeaderAdmin:
    row = await _row(db)
    if row is None:
        row = SiteHeader(slug=HEADER_SLUG)
        db.add(row)
    row.items = payload.model_dump(mode="json")["items"]
    await db.commit()
    return await admin_view(db)


async def reset(db: AsyncSession) -> HeaderAdmin:
    """Drop the saved menu so the built-in links apply again."""
    row = await _row(db)
    if row is not None:
        await db.delete(row)
        await db.commit()
    return _defaults()
