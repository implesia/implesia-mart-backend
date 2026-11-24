import copy

from fastapi import UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.site_header import SiteHeader
from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.site_footer import FooterLink
from app.schemas.site_header import HeaderAdmin, HeaderPublic, HeaderWrite
from app.services.image_storage import delete_owned_media, read_image, store_image
from app.services.site_header_defaults import DEFAULT_ITEMS

HEADER_SLUG = "main"
_FOLDER = "header"
_PREFIX = f"/media/{_FOLDER}/"

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
    logo = row.logo_src if cover_ref_ok(row.logo_src) else ""
    return HeaderAdmin(
        items=items,
        logo_src=logo,
        logo_alt=row.logo_alt if logo else "",
        is_default=False,
        logo_needs_upload=bool(row.logo_src) and not logo,
    )


async def public_view(db: AsyncSession) -> HeaderPublic:
    admin = await admin_view(db)
    return HeaderPublic(
        items=[item for item in admin.items if item.enabled],
        logo_src=admin.logo_src,
        logo_alt=admin.logo_alt,
    )


def _owned(path: str) -> bool:
    return bool(path) and path.startswith(_PREFIX) and cover_ref_ok(path)


async def update(db: AsyncSession, payload: HeaderWrite) -> HeaderAdmin:
    row = await _row(db)
    previous = ""
    if row is None:
        row = SiteHeader(slug=HEADER_SLUG)
        db.add(row)
    else:
        previous = row.logo_src
    row.items = payload.model_dump(mode="json")["items"]
    row.logo_src = payload.logo_src
    row.logo_alt = payload.logo_alt
    await db.commit()
    if previous != payload.logo_src and _owned(previous):
        delete_owned_media({previous}, folder=_FOLDER)  # the replaced logo is no longer used
    return await admin_view(db)


async def reset(db: AsyncSession) -> HeaderAdmin:
    """Drop the saved menu and logo so the built-in ones apply again."""
    row = await _row(db)
    if row is not None:
        previous = row.logo_src
        await db.delete(row)
        await db.commit()
        if _owned(previous):
            delete_owned_media({previous}, folder=_FOLDER)
    return _defaults()


async def upload_logo(upload: UploadFile) -> str:
    if not upload.filename:
        raise UnprocessableError("Choose an image file.")
    return store_image(await read_image(upload), folder=_FOLDER)
