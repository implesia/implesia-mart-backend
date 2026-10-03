import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.privacy.rights import PrivacyRightItem, PrivacyRights
from app.schemas.privacy.rights import (
    ItemPublic,
    ItemRead,
    ItemWrite,
    NotePublic,
    NoteRead,
    RightsAdmin,
    RightsPublic,
    RightsWrite,
)

SECTION_SLUG = "rights"
MAX_ITEMS = 12
EMPTY_NOTE = NotePublic(title="", body="")
EMPTY = RightsPublic(
    icon="",
    nav_label="",
    heading="",
    intro="",
    items=[],
    retention=EMPTY_NOTE,
    updates=EMPTY_NOTE,
)


def _note(active: bool, title: str, body: str, *, admin: bool) -> NotePublic | NoteRead:
    shown = NotePublic(title=title, body=body) if active or admin else EMPTY_NOTE
    if admin:
        return NoteRead(is_active=active, title=title, body=body)
    return shown


def _admin(row: PrivacyRights, items: list[PrivacyRightItem]) -> RightsAdmin:
    return RightsAdmin(
        is_active=row.is_active,
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        intro=row.intro,
        items=[
            ItemRead(
                id=str(item.id),
                icon=item.icon,
                title=item.title,
                description=item.description,
                is_active=item.is_active,
            )
            for item in items
        ],
        retention=NoteRead(
            is_active=row.retention_is_active,
            title=row.retention_title,
            body=row.retention_body,
        ),
        updates=NoteRead(
            is_active=row.updates_is_active,
            title=row.updates_title,
            body=row.updates_body,
        ),
    )


def _public(row: PrivacyRights, items: list[PrivacyRightItem]) -> RightsPublic:
    if not row.is_active or not row.heading:
        return EMPTY
    return RightsPublic(
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        intro=row.intro,
        items=[
            ItemPublic(
                id=str(item.id),
                icon=item.icon,
                title=item.title,
                description=item.description,
            )
            for item in items
            if item.is_active and item.title
        ],
        retention=_note(
            row.retention_is_active, row.retention_title, row.retention_body, admin=False
        ),
        updates=_note(row.updates_is_active, row.updates_title, row.updates_body, admin=False),
    )


async def _items(db: AsyncSession, rights_id: uuid.UUID) -> list[PrivacyRightItem]:
    rows = await db.scalars(
        select(PrivacyRightItem)
        .where(PrivacyRightItem.rights_id == rights_id)
        .order_by(PrivacyRightItem.sort_order, PrivacyRightItem.created_at)
    )
    return list(rows)


async def ensure_rights(db: AsyncSession) -> PrivacyRights:
    row = await db.scalar(select(PrivacyRights).where(PrivacyRights.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = PrivacyRights(
        slug=SECTION_SLUG,
        is_active=True,
        retention_is_active=True,
        updates_is_active=True,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> RightsAdmin:
    row = await ensure_rights(db)
    return _admin(row, await _items(db, row.id))


async def public_view(db: AsyncSession) -> RightsPublic:
    row = await ensure_rights(db)
    return _public(row, await _items(db, row.id))


def _check(payload: RightsWrite) -> None:
    if not payload.heading:
        raise UnprocessableError("Heading is required.")
    if len(payload.items) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 rights.")
    if any(not item.title for item in payload.items):
        raise UnprocessableError("Every right needs a title.")


def _match(
    raw: str | None,
    existing: dict[uuid.UUID, PrivacyRightItem],
) -> PrivacyRightItem | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _apply(
    db: AsyncSession,
    rights_id: uuid.UUID,
    items: list[ItemWrite],
    existing: dict[uuid.UUID, PrivacyRightItem],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                PrivacyRightItem(
                    rights_id=rights_id,
                    icon=item.icon,
                    title=item.title,
                    description=item.description,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.icon = item.icon
        current.title = item.title
        current.description = item.description
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


async def update_rights(db: AsyncSession, payload: RightsWrite) -> RightsAdmin:
    _check(payload)
    row = await ensure_rights(db)
    row.is_active = payload.is_active
    row.icon = payload.icon
    row.nav_label = payload.nav_label
    row.heading = payload.heading
    row.intro = payload.intro
    row.retention_is_active = payload.retention.is_active
    row.retention_title = payload.retention.title
    row.retention_body = payload.retention.body
    row.updates_is_active = payload.updates.is_active
    row.updates_title = payload.updates.title
    row.updates_body = payload.updates.body
    stored = {item.id: item for item in await _items(db, row.id)}
    _apply(db, row.id, payload.items, stored)
    for extra in stored.values():
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _items(db, row.id))
