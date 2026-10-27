import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_contact import SiteContact
from app.schemas.site_contact import (
    SiteContactAdmin,
    SiteContactPublic,
    SiteContactWrite,
    normalize_email,
    normalize_phone,
)

CONTACT_SLUG = "main"

# Built-in values, used only until an admin saves, or if the stored row is ever unreadable.
DEFAULT_PHONE = "01580569129"
DEFAULT_WHATSAPP = "01580569129"
DEFAULT_EMAIL = "implesiamart@gmail.com"

_WA_ME = re.compile(r"https://wa\.me/\d+", re.IGNORECASE)
_TEL = re.compile(r"tel:\+?[\d\s\-().]+$", re.IGNORECASE)


def international(local: str) -> str:
    """01580569129 -> 8801580569129 (wa.me digits, no plus)."""
    return f"880{local[1:]}"


def _public(phone: str, whatsapp: str, email: str) -> SiteContactPublic:
    return SiteContactPublic(
        phone=phone,
        whatsapp=whatsapp,
        email=email,
        tel_href=f"tel:+{international(phone)}",
        whatsapp_href=f"https://wa.me/{international(whatsapp)}",
        mailto_href=f"mailto:{email}",
    )


def defaults() -> SiteContactAdmin:
    return SiteContactAdmin(
        **_public(DEFAULT_PHONE, DEFAULT_WHATSAPP, DEFAULT_EMAIL).model_dump(), is_default=True
    )


async def _row(db: AsyncSession) -> SiteContact | None:
    return await db.scalar(select(SiteContact).where(SiteContact.slug == CONTACT_SLUG))


async def admin_view(db: AsyncSession) -> SiteContactAdmin:
    row = await _row(db)
    if row is None:
        return defaults()
    phone, whatsapp, email = (
        normalize_phone(row.phone),
        normalize_phone(row.whatsapp),
        normalize_email(row.email),
    )
    if phone is None or whatsapp is None or email is None:
        return defaults()  # a bad stored row never breaks the storefront
    return SiteContactAdmin(**_public(phone, whatsapp, email).model_dump())


async def public_view(db: AsyncSession) -> SiteContactPublic:
    admin = await admin_view(db)
    return SiteContactPublic(**admin.model_dump(exclude={"is_default"}))


async def update(db: AsyncSession, payload: SiteContactWrite) -> SiteContactAdmin:
    row = await _row(db)
    if row is None:
        row = SiteContact(slug=CONTACT_SLUG, phone="", whatsapp="", email="")
        db.add(row)
    row.phone, row.whatsapp, row.email = payload.phone, payload.whatsapp, payload.email
    await db.commit()
    return await admin_view(db)


def rewrite_href(href: str, contact: SiteContactPublic) -> str:
    """Point a stored `wa.me` or `tel:` link at the central number.

    A WhatsApp link keeps its `?text=` message. Site paths, mailto: and other http(s) links
    are returned untouched, so only phone/WhatsApp targets follow the central setting.
    """
    if _WA_ME.match(href):
        parts = urlsplit(href)
        return contact.whatsapp_href + (f"?{parts.query}" if parts.query else "")
    if _TEL.match(href):
        return contact.tel_href
    return href


def channel_for_icon(
    icon: str, value: str, href: str, contact: SiteContactPublic
) -> tuple[str, str]:
    """Value and link for a contact channel row, following the central setting by icon."""
    if icon == "call":
        return contact.phone, contact.tel_href
    if icon == "chat":
        chat = rewrite_href(href, contact) if _WA_ME.match(href) else contact.whatsapp_href
        return contact.whatsapp, chat
    if icon == "mail":
        return contact.email, contact.mailto_href
    return value, href
