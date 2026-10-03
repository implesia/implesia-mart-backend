from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.contact.details import ContactDetailChannel, ContactDetails
from app.schemas.contact.details import (
    ChannelPublic,
    ChannelRead,
    DetailsAdmin,
    DetailsPublic,
    DetailsWrite,
    SocialPublic,
    SocialRead,
    SocialWrite,
)
from app.services.contact.hero_service import _safe_href

SECTION_SLUG = "contact"
MAX_CHANNELS = 12
EMPTY = DetailsPublic(title="", subtitle="", badge="", channels=[], social=[])


def _check_href(href: str, kind: str) -> None:
    if not href:
        return
    try:
        _safe_href(href)
    except UnprocessableError as exc:
        raise UnprocessableError(exc.message.replace("Button", kind)) from exc


def _social_pair(row: ContactDetails) -> list[SocialRead]:
    return [
        SocialRead(
            platform="facebook",
            label=row.facebook_label,
            href=row.facebook_href,
            is_active=row.facebook_active,
        ),
        SocialRead(
            platform="linkedin",
            label=row.linkedin_label,
            href=row.linkedin_href,
            is_active=row.linkedin_active,
        ),
    ]


def _admin(
    row: ContactDetails, channels: list[ContactDetailChannel]
) -> DetailsAdmin:
    return DetailsAdmin(
        is_active=row.is_active,
        title=row.title,
        subtitle=row.subtitle,
        badge=row.badge,
        channels=[
            ChannelRead(
                id=str(channel.id),
                icon=channel.icon,
                title=channel.title,
                value=channel.value,
                href=channel.href,
                is_active=channel.is_active,
            )
            for channel in channels
        ],
        social=_social_pair(row),
    )


def _public(row: ContactDetails, channels: list[ContactDetailChannel]) -> DetailsPublic:
    if not row.is_active or not row.title:
        return EMPTY
    social = [
        SocialPublic(platform=item.platform, label=item.label, href=item.href)
        for item in _social_pair(row)
        if item.is_active and item.href
    ]
    return DetailsPublic(
        title=row.title,
        subtitle=row.subtitle,
        badge=row.badge,
        channels=[
            ChannelPublic(
                id=str(channel.id),
                icon=channel.icon,
                title=channel.title,
                value=channel.value,
                href=channel.href,
            )
            for channel in channels
            if channel.is_active
        ],
        social=social,
    )


async def _channels(db: AsyncSession, details_id: object) -> list[ContactDetailChannel]:
    rows = await db.scalars(
        select(ContactDetailChannel)
        .where(ContactDetailChannel.details_id == details_id)
        .order_by(ContactDetailChannel.sort_order, ContactDetailChannel.created_at)
    )
    return list(rows)


async def ensure_details(db: AsyncSession) -> ContactDetails:
    row = await db.scalar(select(ContactDetails).where(ContactDetails.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ContactDetails(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> DetailsAdmin:
    row = await ensure_details(db)
    return _admin(row, await _channels(db, row.id))


async def public_view(db: AsyncSession) -> DetailsPublic:
    row = await ensure_details(db)
    return _public(row, await _channels(db, row.id))


def _check(payload: DetailsWrite) -> None:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if len(payload.channels) > MAX_CHANNELS:
        raise UnprocessableError("You can add up to 12 channels.")
    if any(not item.title or not item.value or not item.href for item in payload.channels):
        raise UnprocessableError("Each channel needs a title, a value, and a link.")
    for item in payload.channels:
        _check_href(item.href, "Channel")
    platforms = [item.platform for item in payload.social]
    if len(platforms) != len(set(platforms)):
        raise UnprocessableError("Each social network can only be saved once.")
    for item in payload.social:
        _check_href(item.href, "Social")


def _apply_social(row: ContactDetails, social: list[SocialWrite]) -> None:
    found = {item.platform: item for item in social}
    facebook = found.get("facebook")
    linkedin = found.get("linkedin")
    row.facebook_label = facebook.label if facebook else ""
    row.facebook_href = facebook.href if facebook else ""
    row.facebook_active = facebook.is_active if facebook else False
    row.linkedin_label = linkedin.label if linkedin else ""
    row.linkedin_href = linkedin.href if linkedin else ""
    row.linkedin_active = linkedin.is_active if linkedin else False


async def update_details(db: AsyncSession, payload: DetailsWrite) -> DetailsAdmin:
    _check(payload)
    row = await ensure_details(db)
    row.is_active = payload.is_active
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.badge = payload.badge
    _apply_social(row, payload.social)
    existing = await _channels(db, row.id)
    for index, item in enumerate(payload.channels):
        if index < len(existing):
            current = existing[index]
            current.icon = item.icon or "call"
            current.title = item.title
            current.value = item.value
            current.href = item.href
            current.is_active = item.is_active
            current.sort_order = index
        else:
            db.add(
                ContactDetailChannel(
                    details_id=row.id,
                    icon=item.icon or "call",
                    title=item.title,
                    value=item.value,
                    href=item.href,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
    for extra in existing[len(payload.channels) :]:
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _channels(db, row.id))
