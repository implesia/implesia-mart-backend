import copy
from typing import Any

from fastapi import UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.site_footer import SiteFooter
from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.site_footer import (
    FooterAdmin,
    FooterLink,
    FooterPublic,
    FooterSection,
    FooterWrite,
    TrustPoint,
)
from app.services.image_storage import delete_owned_media, read_image, store_image
from app.services.site_footer_defaults import DEFAULTS

FOOTER_SLUG = "main"
_FOLDER = "footer"
_PREFIX = f"/media/{_FOLDER}/"

_SECTIONS = TypeAdapter(list[FooterSection])
_TRUST = TypeAdapter(list[TrustPoint])
_LINKS = TypeAdapter(list[FooterLink])


async def _row(db: AsyncSession) -> SiteFooter | None:
    return await db.scalar(select(SiteFooter).where(SiteFooter.slug == FOOTER_SLUG))


def _list(adapter: TypeAdapter[Any], raw: Any, default: list[Any]) -> list[Any]:
    """A stored list that still validates, else the built-in default. A bad row never breaks
    the storefront. An empty saved list is respected (the editor cleared it on purpose)."""
    try:
        return adapter.validate_python(raw)
    except ValidationError:
        return adapter.validate_python(copy.deepcopy(default))


def _admin_from_defaults() -> FooterAdmin:
    return FooterAdmin(
        **{
            **copy.deepcopy(DEFAULTS),
            "sections": _SECTIONS.validate_python(copy.deepcopy(DEFAULTS["sections"])),
            "trust_points": _TRUST.validate_python(copy.deepcopy(DEFAULTS["trust_points"])),
            "legal_links": _LINKS.validate_python(copy.deepcopy(DEFAULTS["legal_links"])),
        },
        is_default=True,
    )


def _text(value: str, fallback: str) -> str:
    return value if value.strip() else fallback


async def admin_view(db: AsyncSession) -> FooterAdmin:
    row = await _row(db)
    if row is None:
        return _admin_from_defaults()
    logo = row.logo_src if cover_ref_ok(row.logo_src) else ""
    return FooterAdmin(
        brand_name=_text(row.brand_name, DEFAULTS["brand_name"]),
        description=row.description,
        logo_src=logo,
        logo_alt=row.logo_alt if logo else "",
        address=row.address,
        copyright_text=_text(row.copyright_text, DEFAULTS["copyright_text"]),
        show_contact=row.show_contact,
        show_social=row.show_social,
        show_whatsapp_cta=row.show_whatsapp_cta,
        sections=_list(_SECTIONS, row.sections, DEFAULTS["sections"]),
        trust_points=_list(_TRUST, row.trust_points, DEFAULTS["trust_points"]),
        legal_links=_list(_LINKS, row.legal_links, DEFAULTS["legal_links"]),
        is_default=False,
        logo_needs_upload=bool(row.logo_src) and not logo,
    )


async def public_view(db: AsyncSession) -> FooterPublic:
    """The live footer: only enabled items; sections with no enabled link are dropped."""
    admin = await admin_view(db)
    sections = []
    for section in admin.sections:
        links = [link for link in section.links if link.enabled]
        if section.enabled and links:
            sections.append(section.model_copy(update={"links": links}))
    return FooterPublic(
        brand_name=admin.brand_name,
        description=admin.description,
        logo_src=admin.logo_src,
        logo_alt=admin.logo_alt,
        address=admin.address,
        copyright_text=admin.copyright_text,
        show_contact=admin.show_contact,
        show_social=admin.show_social,
        show_whatsapp_cta=admin.show_whatsapp_cta,
        sections=sections,
        trust_points=[point for point in admin.trust_points if point.enabled],
        legal_links=[link for link in admin.legal_links if link.enabled],
    )


async def update(db: AsyncSession, payload: FooterWrite) -> FooterAdmin:
    row = await _row(db)
    previous = ""
    if row is None:
        row = SiteFooter(slug=FOOTER_SLUG)
        db.add(row)
    else:
        previous = row.logo_src
    data = payload.model_dump(mode="json")
    for field, value in data.items():
        setattr(row, field, value)
    await db.commit()
    if (
        previous
        and previous != payload.logo_src
        and previous.startswith(_PREFIX)
        and cover_ref_ok(previous)
    ):
        delete_owned_media({previous}, folder=_FOLDER)
    return await admin_view(db)


async def reset(db: AsyncSession) -> FooterAdmin:
    """Drop the saved footer so the built-in defaults apply again."""
    row = await _row(db)
    if row is not None:
        previous = row.logo_src
        await db.delete(row)
        await db.commit()
        if previous.startswith(_PREFIX) and cover_ref_ok(previous):
            delete_owned_media({previous}, folder=_FOLDER)
    return _admin_from_defaults()


async def upload_logo(upload: UploadFile) -> str:
    if not upload.filename:
        raise UnprocessableError("Choose an image file.")
    return store_image(await read_image(upload), folder=_FOLDER)
