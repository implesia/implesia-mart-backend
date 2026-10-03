from urllib.parse import unquote, urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.blogs.cta import BlogCta
from app.schemas.blogs.cta import CtaAdmin, CtaPublic, CtaWrite

SECTION_SLUG = "blogs"
EMPTY = CtaPublic(
    title="",
    subtitle="",
    primary_label="",
    primary_href="",
    secondary_label="",
    secondary_href="",
)
_BLOCKED_SCHEMES = ("javascript:", "data:", "vbscript:", "file:", "blob:")


def present(row: BlogCta) -> CtaAdmin:
    return CtaAdmin(
        is_active=row.is_active,
        title=row.title,
        subtitle=row.subtitle,
        primary_label=row.primary_label,
        primary_href=row.primary_href,
        secondary_label=row.secondary_label,
        secondary_href=row.secondary_href,
    )


def present_public(row: BlogCta) -> CtaPublic:
    if not row.is_active or not row.title:
        return EMPTY
    shown = present(row)
    return CtaPublic(
        title=shown.title,
        subtitle=shown.subtitle,
        primary_label=shown.primary_label,
        primary_href=shown.primary_href,
        secondary_label=shown.secondary_label,
        secondary_href=shown.secondary_href,
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


async def ensure_cta(db: AsyncSession) -> BlogCta:
    row = await db.scalar(select(BlogCta).where(BlogCta.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = BlogCta(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> CtaAdmin:
    return present(await ensure_cta(db))


async def public_view(db: AsyncSession) -> CtaPublic:
    return present_public(await ensure_cta(db))


async def update_cta(db: AsyncSession, payload: CtaWrite) -> CtaAdmin:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    _safe_href(payload.primary_href)
    _safe_href(payload.secondary_href)
    row = await ensure_cta(db)
    row.is_active = payload.is_active
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.primary_label = payload.primary_label
    row.primary_href = payload.primary_href
    row.secondary_label = payload.secondary_label
    row.secondary_href = payload.secondary_href
    await db.commit()
    await db.refresh(row)
    return present(row)
