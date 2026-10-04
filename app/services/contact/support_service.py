import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.contact.support import ContactSupport, ContactSupportHour, ContactSupportLink
from app.schemas.contact.support import (
    HourPublic,
    HourRead,
    HourWrite,
    LinkPublic,
    LinkRead,
    LinkWrite,
    SupportAdmin,
    SupportPublic,
    SupportWrite,
)
from app.services.contact.hero_service import _safe_href

SECTION_SLUG = "contact"
MAX_ROWS = 12
EMPTY = SupportPublic(title="", subtitle="", hours=[], quick_links=[])


def _check_href(href: str) -> None:
    if not href:
        return
    try:
        _safe_href(href)
    except UnprocessableError as exc:
        raise UnprocessableError(exc.message.replace("Button link", "Link")) from exc


def _admin(
    row: ContactSupport,
    hours: list[ContactSupportHour],
    links: list[ContactSupportLink],
) -> SupportAdmin:
    return SupportAdmin(
        is_active=row.is_active,
        title=row.title,
        subtitle=row.subtitle,
        hours=[
            HourRead(
                id=str(item.id),
                label=item.label,
                value=item.value,
                is_active=item.is_active,
            )
            for item in hours
        ],
        quick_links=[
            LinkRead(
                id=str(item.id),
                icon=item.icon,
                label=item.label,
                href=item.href,
                is_active=item.is_active,
            )
            for item in links
        ],
    )


def _public(
    row: ContactSupport,
    hours: list[ContactSupportHour],
    links: list[ContactSupportLink],
) -> SupportPublic:
    if not row.is_active or not row.title:
        return EMPTY
    return SupportPublic(
        title=row.title,
        subtitle=row.subtitle,
        hours=[
            HourPublic(id=str(item.id), label=item.label, value=item.value)
            for item in hours
            if item.is_active
        ],
        quick_links=[
            LinkPublic(id=str(item.id), icon=item.icon, label=item.label, href=item.href)
            for item in links
            if item.is_active
        ],
    )


async def _ordered[T](db: AsyncSession, model: type[T], support_id: uuid.UUID) -> list[T]:
    rows = await db.scalars(
        select(model)
        .where(model.support_id == support_id)  # type: ignore[attr-defined]
        .order_by(model.sort_order, model.created_at)  # type: ignore[attr-defined]
    )
    return list(rows)


async def ensure_support(db: AsyncSession) -> ContactSupport:
    row = await db.scalar(select(ContactSupport).where(ContactSupport.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ContactSupport(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> SupportAdmin:
    row = await ensure_support(db)
    return _admin(
        row,
        await _ordered(db, ContactSupportHour, row.id),
        await _ordered(db, ContactSupportLink, row.id),
    )


async def public_view(db: AsyncSession) -> SupportPublic:
    row = await ensure_support(db)
    return _public(
        row,
        await _ordered(db, ContactSupportHour, row.id),
        await _ordered(db, ContactSupportLink, row.id),
    )


def _check(payload: SupportWrite) -> None:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if len(payload.hours) > MAX_ROWS or len(payload.quick_links) > MAX_ROWS:
        raise UnprocessableError("You can add up to 12 rows.")
    if any(not item.label or not item.value for item in payload.hours):
        raise UnprocessableError("Each row needs a day and the hours.")
    if any(not item.label or not item.href for item in payload.quick_links):
        raise UnprocessableError("Each link needs a label and a destination.")
    for item in payload.quick_links:
        _check_href(item.href)


def _sync_hours(
    db: AsyncSession,
    row: ContactSupport,
    existing: list[ContactSupportHour],
    payload: list[HourWrite],
) -> None:
    for index, item in enumerate(payload):
        if index < len(existing):
            current = existing[index]
            current.label = item.label
            current.value = item.value
            current.is_active = item.is_active
            current.sort_order = index
        else:
            db.add(
                ContactSupportHour(
                    support_id=row.id,
                    label=item.label,
                    value=item.value,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )


def _sync_links(
    db: AsyncSession,
    row: ContactSupport,
    existing: list[ContactSupportLink],
    payload: list[LinkWrite],
) -> None:
    for index, item in enumerate(payload):
        if index < len(existing):
            current = existing[index]
            current.icon = item.icon or "help"
            current.label = item.label
            current.href = item.href
            current.is_active = item.is_active
            current.sort_order = index
        else:
            db.add(
                ContactSupportLink(
                    support_id=row.id,
                    icon=item.icon or "help",
                    label=item.label,
                    href=item.href,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )


async def update_support(db: AsyncSession, payload: SupportWrite) -> SupportAdmin:
    _check(payload)
    row = await ensure_support(db)
    row.is_active = payload.is_active
    row.title = payload.title
    row.subtitle = payload.subtitle
    hours = await _ordered(db, ContactSupportHour, row.id)
    links = await _ordered(db, ContactSupportLink, row.id)
    _sync_hours(db, row, hours, payload.hours)
    _sync_links(db, row, links, payload.quick_links)
    for extra in hours[len(payload.hours) :]:
        await db.delete(extra)
    for stale in links[len(payload.quick_links) :]:
        await db.delete(stale)
    await db.commit()
    await db.refresh(row)
    return _admin(
        row,
        await _ordered(db, ContactSupportHour, row.id),
        await _ordered(db, ContactSupportLink, row.id),
    )
