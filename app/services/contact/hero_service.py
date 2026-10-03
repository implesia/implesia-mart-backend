from urllib.parse import quote, unquote, urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.contact.hero import ContactHero
from app.schemas.contact.hero import HeroAdmin, HeroLink, HeroPublic, HeroWrite

SECTION_SLUG = "contact"
DEFAULT_EYEBROW = "যোগাযোগ"
DEFAULT_TITLE = "অর্ডার বা প্রোডাক্ট নিয়ে সাহায্য লাগলে বলুন"
DEFAULT_SUBTITLE = (
    "কল বা হোয়াটসঅ্যাপে সরাসরি যোগাযোগ করুন। কর্মঘণ্টায় রিপ্লাই দেওয়ার চেষ্টা করি।"
)
DEFAULT_PRIMARY_LABEL = "হোয়াটসঅ্যাপ"
DEFAULT_PRIMARY_HREF = (
    "https://wa.me/8801516527932?text="
    + quote("হ্যালো, আমি ইমপ্লেসিয়া মার্ট সম্পর্কে জানতে চাই।")
)
DEFAULT_SECONDARY_LABEL = "কল করুন"
DEFAULT_SECONDARY_HREF = "tel:+8801516527932"
_BLOCKED_SCHEMES = ("javascript:", "data:", "vbscript:", "file:", "blob:")
EMPTY = HeroPublic(
    eyebrow="",
    title="",
    subtitle="",
    primary_cta=HeroLink(label="", href=""),
    secondary_cta=HeroLink(label="", href=""),
)


def present(row: ContactHero) -> HeroAdmin:
    return HeroAdmin(
        is_active=row.is_active,
        eyebrow=row.eyebrow,
        title=row.title,
        subtitle=row.subtitle,
        primary_cta=HeroLink(label=row.primary_label, href=row.primary_href),
        secondary_cta=HeroLink(label=row.secondary_label, href=row.secondary_href),
    )


def present_public(row: ContactHero) -> HeroPublic:
    if not row.is_active:
        return EMPTY
    shown = present(row)
    return HeroPublic(
        eyebrow=shown.eyebrow,
        title=shown.title,
        subtitle=shown.subtitle,
        primary_cta=shown.primary_cta,
        secondary_cta=shown.secondary_cta,
    )


def _safe_href(href: str) -> None:
    if not href:
        return
    if any(char.isspace() for char in href) or "\\" in href:
        raise UnprocessableError("Button link is not allowed")
    decoded = unquote(unquote(href))
    lowered = decoded.lower()
    if lowered.startswith(_BLOCKED_SCHEMES):
        raise UnprocessableError("Button link is not allowed")
    if href.startswith(("tel:", "mailto:", "sms:")):
        return
    if href.startswith("/") and not href.startswith("//"):
        if ".." in decoded.split("/"):
            raise UnprocessableError("Button link is not allowed")
        return
    parsed = urlsplit(href)
    host = (parsed.hostname or "").lower()
    local = host in {"localhost", "127.0.0.1"}
    if parsed.username or parsed.password or not host:
        raise UnprocessableError("Button link is not allowed")
    if parsed.scheme == "https" or (parsed.scheme == "http" and local):
        return
    raise UnprocessableError("Button link must be a site path, https, tel, or mailto link")


async def ensure_hero(db: AsyncSession) -> ContactHero:
    row = await db.scalar(select(ContactHero).where(ContactHero.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ContactHero(
        slug=SECTION_SLUG,
        is_active=True,
        eyebrow=DEFAULT_EYEBROW,
        title=DEFAULT_TITLE,
        subtitle=DEFAULT_SUBTITLE,
        primary_label=DEFAULT_PRIMARY_LABEL,
        primary_href=DEFAULT_PRIMARY_HREF,
        secondary_label=DEFAULT_SECONDARY_LABEL,
        secondary_href=DEFAULT_SECONDARY_HREF,
    )
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
    _safe_href(payload.primary_cta.href)
    _safe_href(payload.secondary_cta.href)
    row = await ensure_hero(db)
    row.is_active = payload.is_active
    row.eyebrow = payload.eyebrow
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.primary_label = payload.primary_cta.label
    row.primary_href = payload.primary_cta.href
    row.secondary_label = payload.secondary_cta.label
    row.secondary_href = payload.secondary_cta.href
    await db.commit()
    await db.refresh(row)
    return present(row)
