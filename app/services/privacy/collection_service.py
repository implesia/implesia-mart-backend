import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.privacy.collection import PrivacyCollection, PrivacyCollectionCard
from app.schemas.privacy.collection import (
    CardPublic,
    CardRead,
    CardWrite,
    CollectionAdmin,
    CollectionPublic,
    CollectionWrite,
)

SECTION_SLUG = "collection"
MAX_CARDS = 12
EMPTY = CollectionPublic(icon="", nav_label="", heading="", intro="", cards=[])


def _admin(row: PrivacyCollection, cards: list[PrivacyCollectionCard]) -> CollectionAdmin:
    return CollectionAdmin(
        is_active=row.is_active,
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        intro=row.intro,
        cards=[
            CardRead(
                id=str(item.id),
                icon=item.icon,
                title=item.title,
                description=item.description,
                is_active=item.is_active,
            )
            for item in cards
        ],
    )


def _public(row: PrivacyCollection, cards: list[PrivacyCollectionCard]) -> CollectionPublic:
    if not row.is_active or not row.heading:
        return EMPTY
    return CollectionPublic(
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        intro=row.intro,
        cards=[
            CardPublic(
                id=str(item.id),
                icon=item.icon,
                title=item.title,
                description=item.description,
            )
            for item in cards
            if item.is_active and item.title
        ],
    )


async def _cards(db: AsyncSession, collection_id: uuid.UUID) -> list[PrivacyCollectionCard]:
    rows = await db.scalars(
        select(PrivacyCollectionCard)
        .where(PrivacyCollectionCard.collection_id == collection_id)
        .order_by(PrivacyCollectionCard.sort_order, PrivacyCollectionCard.created_at)
    )
    return list(rows)


async def ensure_collection(db: AsyncSession) -> PrivacyCollection:
    row = await db.scalar(select(PrivacyCollection).where(PrivacyCollection.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = PrivacyCollection(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> CollectionAdmin:
    row = await ensure_collection(db)
    return _admin(row, await _cards(db, row.id))


async def public_view(db: AsyncSession) -> CollectionPublic:
    row = await ensure_collection(db)
    return _public(row, await _cards(db, row.id))


def _check(payload: CollectionWrite) -> None:
    if not payload.heading:
        raise UnprocessableError("Heading is required.")
    if len(payload.cards) > MAX_CARDS:
        raise UnprocessableError("You can add up to 12 cards.")
    if any(not item.title for item in payload.cards):
        raise UnprocessableError("Every card needs a title.")


def _match(
    raw: str | None,
    existing: dict[uuid.UUID, PrivacyCollectionCard],
) -> PrivacyCollectionCard | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _apply(
    db: AsyncSession,
    collection_id: uuid.UUID,
    items: list[CardWrite],
    existing: dict[uuid.UUID, PrivacyCollectionCard],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                PrivacyCollectionCard(
                    collection_id=collection_id,
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


async def update_collection(db: AsyncSession, payload: CollectionWrite) -> CollectionAdmin:
    _check(payload)
    row = await ensure_collection(db)
    row.is_active = payload.is_active
    row.icon = payload.icon
    row.nav_label = payload.nav_label
    row.heading = payload.heading
    row.intro = payload.intro
    stored = {item.id: item for item in await _cards(db, row.id)}
    _apply(db, row.id, payload.cards, stored)
    for extra in stored.values():
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _cards(db, row.id))
