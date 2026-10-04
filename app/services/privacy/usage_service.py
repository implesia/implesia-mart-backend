import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.privacy.usage import PrivacyUsage, PrivacyUsageBadge, PrivacyUsageItem
from app.schemas.privacy.usage import (
    BadgePublic,
    BadgeRead,
    BadgeWrite,
    ItemPublic,
    ItemRead,
    ItemWrite,
    ProtectionPublic,
    ProtectionRead,
    UsageAdmin,
    UsagePublic,
    UsageWrite,
)

SECTION_SLUG = "usage"
MAX_ITEMS = 12
EMPTY_PROTECTION = ProtectionPublic(icon="", title="", body="", badges=[])
EMPTY = UsagePublic(
    icon="", nav_label="", heading="", intro="", items=[], protection=EMPTY_PROTECTION
)


def _admin(
    row: PrivacyUsage,
    items: list[PrivacyUsageItem],
    badges: list[PrivacyUsageBadge],
) -> UsageAdmin:
    return UsageAdmin(
        is_active=row.is_active,
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        intro=row.intro,
        items=[
            ItemRead(
                id=str(item.id),
                title=item.title,
                description=item.description,
                is_active=item.is_active,
            )
            for item in items
        ],
        protection=ProtectionRead(
            is_active=row.protection_is_active,
            icon=row.protection_icon,
            title=row.protection_title,
            body=row.protection_body,
            badges=[
                BadgeRead(
                    id=str(badge.id),
                    icon=badge.icon,
                    label=badge.label,
                    is_active=badge.is_active,
                )
                for badge in badges
            ],
        ),
    )


def _public(
    row: PrivacyUsage,
    items: list[PrivacyUsageItem],
    badges: list[PrivacyUsageBadge],
) -> UsagePublic:
    if not row.is_active or not row.heading:
        return EMPTY
    protection = EMPTY_PROTECTION
    if row.protection_is_active:
        protection = ProtectionPublic(
            icon=row.protection_icon,
            title=row.protection_title,
            body=row.protection_body,
            badges=[
                BadgePublic(id=str(badge.id), icon=badge.icon, label=badge.label)
                for badge in badges
                if badge.is_active and badge.label
            ],
        )
    return UsagePublic(
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        intro=row.intro,
        items=[
            ItemPublic(id=str(item.id), title=item.title, description=item.description)
            for item in items
            if item.is_active and item.title
        ],
        protection=protection,
    )


async def _items(db: AsyncSession, usage_id: uuid.UUID) -> list[PrivacyUsageItem]:
    rows = await db.scalars(
        select(PrivacyUsageItem)
        .where(PrivacyUsageItem.usage_id == usage_id)
        .order_by(PrivacyUsageItem.sort_order, PrivacyUsageItem.created_at)
    )
    return list(rows)


async def _badges(db: AsyncSession, usage_id: uuid.UUID) -> list[PrivacyUsageBadge]:
    rows = await db.scalars(
        select(PrivacyUsageBadge)
        .where(PrivacyUsageBadge.usage_id == usage_id)
        .order_by(PrivacyUsageBadge.sort_order, PrivacyUsageBadge.created_at)
    )
    return list(rows)


async def ensure_usage(db: AsyncSession) -> PrivacyUsage:
    row = await db.scalar(select(PrivacyUsage).where(PrivacyUsage.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = PrivacyUsage(slug=SECTION_SLUG, is_active=True, protection_is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> UsageAdmin:
    row = await ensure_usage(db)
    return _admin(row, await _items(db, row.id), await _badges(db, row.id))


async def public_view(db: AsyncSession) -> UsagePublic:
    row = await ensure_usage(db)
    return _public(row, await _items(db, row.id), await _badges(db, row.id))


def _check(payload: UsageWrite) -> None:
    if not payload.heading:
        raise UnprocessableError("Heading is required.")
    if len(payload.items) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 uses.")
    if len(payload.protection.badges) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 badges.")
    blank_item = any(not item.title for item in payload.items)
    blank_badge = any(not badge.label for badge in payload.protection.badges)
    if blank_item or blank_badge:
        raise UnprocessableError("Fill in every use and badge, or remove the empty ones.")


def _match[T](raw: str | None, existing: dict[uuid.UUID, T]) -> T | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _apply_items(
    db: AsyncSession,
    usage_id: uuid.UUID,
    items: list[ItemWrite],
    existing: dict[uuid.UUID, PrivacyUsageItem],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if not isinstance(current, PrivacyUsageItem):
            db.add(
                PrivacyUsageItem(
                    usage_id=usage_id,
                    title=item.title,
                    description=item.description,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.title = item.title
        current.description = item.description
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


def _apply_badges(
    db: AsyncSession,
    usage_id: uuid.UUID,
    badges: list[BadgeWrite],
    existing: dict[uuid.UUID, PrivacyUsageBadge],
) -> None:
    for index, badge in enumerate(badges):
        current = _match(badge.id, existing)
        if not isinstance(current, PrivacyUsageBadge):
            db.add(
                PrivacyUsageBadge(
                    usage_id=usage_id,
                    icon=badge.icon,
                    label=badge.label,
                    is_active=badge.is_active,
                    sort_order=index,
                )
            )
            continue
        current.icon = badge.icon
        current.label = badge.label
        current.is_active = badge.is_active
        current.sort_order = index
        existing.pop(current.id, None)


async def update_usage(db: AsyncSession, payload: UsageWrite) -> UsageAdmin:
    _check(payload)
    row = await ensure_usage(db)
    row.is_active = payload.is_active
    row.icon = payload.icon
    row.nav_label = payload.nav_label
    row.heading = payload.heading
    row.intro = payload.intro
    row.protection_is_active = payload.protection.is_active
    row.protection_icon = payload.protection.icon
    row.protection_title = payload.protection.title
    row.protection_body = payload.protection.body
    stored_items = {item.id: item for item in await _items(db, row.id)}
    stored_badges = {badge.id: badge for badge in await _badges(db, row.id)}
    _apply_items(db, row.id, payload.items, stored_items)
    _apply_badges(db, row.id, payload.protection.badges, stored_badges)
    for extra in stored_items.values():
        await db.delete(extra)
    for stale in stored_badges.values():
        await db.delete(stale)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _items(db, row.id), await _badges(db, row.id))
