import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.privacy.sharing import PrivacySharing, PrivacySharingChip
from app.schemas.privacy.sharing import (
    ChipPublic,
    ChipRead,
    ChipWrite,
    SharingAdmin,
    SharingPublic,
    SharingWrite,
)

SECTION_SLUG = "sharing"
MAX_CHIPS = 12
EMPTY = SharingPublic(icon="", nav_label="", heading="", body="", chips=[])


def _admin(row: PrivacySharing, chips: list[PrivacySharingChip]) -> SharingAdmin:
    return SharingAdmin(
        is_active=row.is_active,
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        body=row.body,
        chips=[
            ChipRead(id=str(item.id), label=item.label, is_active=item.is_active) for item in chips
        ],
    )


def _public(row: PrivacySharing, chips: list[PrivacySharingChip]) -> SharingPublic:
    if not row.is_active or not row.heading:
        return EMPTY
    return SharingPublic(
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        body=row.body,
        chips=[
            ChipPublic(id=str(item.id), label=item.label)
            for item in chips
            if item.is_active and item.label
        ],
    )


async def _chips(db: AsyncSession, sharing_id: uuid.UUID) -> list[PrivacySharingChip]:
    rows = await db.scalars(
        select(PrivacySharingChip)
        .where(PrivacySharingChip.sharing_id == sharing_id)
        .order_by(PrivacySharingChip.sort_order, PrivacySharingChip.created_at)
    )
    return list(rows)


async def ensure_sharing(db: AsyncSession) -> PrivacySharing:
    row = await db.scalar(select(PrivacySharing).where(PrivacySharing.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = PrivacySharing(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> SharingAdmin:
    row = await ensure_sharing(db)
    return _admin(row, await _chips(db, row.id))


async def public_view(db: AsyncSession) -> SharingPublic:
    row = await ensure_sharing(db)
    return _public(row, await _chips(db, row.id))


def _check(payload: SharingWrite) -> None:
    if not payload.heading:
        raise UnprocessableError("Heading is required.")
    if len(payload.chips) > MAX_CHIPS:
        raise UnprocessableError("You can add up to 12 chips.")
    if any(not item.label for item in payload.chips):
        raise UnprocessableError("Every chip needs a label, or remove the empty ones.")


def _match(
    raw: str | None,
    existing: dict[uuid.UUID, PrivacySharingChip],
) -> PrivacySharingChip | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _apply(
    db: AsyncSession,
    sharing_id: uuid.UUID,
    items: list[ChipWrite],
    existing: dict[uuid.UUID, PrivacySharingChip],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                PrivacySharingChip(
                    sharing_id=sharing_id,
                    label=item.label,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.label = item.label
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


async def update_sharing(db: AsyncSession, payload: SharingWrite) -> SharingAdmin:
    _check(payload)
    row = await ensure_sharing(db)
    row.is_active = payload.is_active
    row.icon = payload.icon
    row.nav_label = payload.nav_label
    row.heading = payload.heading
    row.body = payload.body
    stored = {item.id: item for item in await _chips(db, row.id)}
    _apply(db, row.id, payload.chips, stored)
    for extra in stored.values():
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _chips(db, row.id))
