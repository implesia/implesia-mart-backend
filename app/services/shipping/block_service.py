import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.shipping.block import (
    ShippingBlock,
    ShippingBlockCard,
    ShippingBlockNote,
    ShippingBlockTime,
)
from app.schemas.shipping.block import (
    BlockAdmin,
    BlockPublic,
    BlockWrite,
    CardPublic,
    CardRead,
    CardWrite,
    NotePublic,
    NoteRead,
    NoteWrite,
    TimePublic,
    TimeRead,
    TimeWrite,
)

SECTION_SLUG = "shipping"
MAX_ITEMS = 12
EMPTY = BlockPublic(
    icon="",
    nav_label="",
    heading="",
    intro="",
    cards=[],
    timelines_title="",
    timelines=[],
    notes=[],
)


def _admin(
    row: ShippingBlock,
    cards: list[ShippingBlockCard],
    times: list[ShippingBlockTime],
    notes: list[ShippingBlockNote],
) -> BlockAdmin:
    return BlockAdmin(
        is_active=row.is_active,
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        intro=row.intro,
        timelines_title=row.timelines_title,
        cards=[
            CardRead(
                id=str(item.id),
                icon=item.icon,
                eyebrow=item.eyebrow,
                title=item.title,
                body=item.body,
                variant=item.variant,
                is_active=item.is_active,
            )
            for item in cards
        ],
        timelines=[
            TimeRead(id=str(item.id), label=item.label, value=item.value, is_active=item.is_active)
            for item in times
        ],
        notes=[
            NoteRead(
                id=str(item.id),
                icon=item.icon,
                title=item.title,
                body=item.body,
                is_active=item.is_active,
            )
            for item in notes
        ],
    )


def _public(
    row: ShippingBlock,
    cards: list[ShippingBlockCard],
    times: list[ShippingBlockTime],
    notes: list[ShippingBlockNote],
) -> BlockPublic:
    if not row.is_active or not row.heading:
        return EMPTY
    return BlockPublic(
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        intro=row.intro,
        timelines_title=row.timelines_title,
        cards=[
            CardPublic(
                id=str(item.id),
                icon=item.icon,
                eyebrow=item.eyebrow,
                title=item.title,
                body=item.body,
                variant=item.variant,
            )
            for item in cards
            if item.is_active
        ],
        timelines=[
            TimePublic(id=str(item.id), label=item.label, value=item.value)
            for item in times
            if item.is_active
        ],
        notes=[
            NotePublic(id=str(item.id), icon=item.icon, title=item.title, body=item.body)
            for item in notes
            if item.is_active
        ],
    )


async def _rows(db: AsyncSession, model: type, block_id: uuid.UUID) -> list:
    rows = await db.scalars(
        select(model)
        .where(model.block_id == block_id)
        .order_by(model.sort_order, model.created_at)
    )
    return list(rows)


async def ensure_block(db: AsyncSession) -> ShippingBlock:
    row = await db.scalar(select(ShippingBlock).where(ShippingBlock.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ShippingBlock(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> BlockAdmin:
    row = await ensure_block(db)
    return _admin(
        row,
        await _rows(db, ShippingBlockCard, row.id),
        await _rows(db, ShippingBlockTime, row.id),
        await _rows(db, ShippingBlockNote, row.id),
    )


async def public_view(db: AsyncSession) -> BlockPublic:
    row = await ensure_block(db)
    return _public(
        row,
        await _rows(db, ShippingBlockCard, row.id),
        await _rows(db, ShippingBlockTime, row.id),
        await _rows(db, ShippingBlockNote, row.id),
    )


def _check(payload: BlockWrite) -> None:
    if not payload.heading:
        raise UnprocessableError("Heading is required.")
    if len(payload.cards) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 cards.")
    if len(payload.timelines) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 times.")
    if len(payload.notes) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 notes.")
    incomplete = (
        any(not item.title for item in payload.cards)
        or any(not item.label or not item.value for item in payload.timelines)
        or any(not item.title for item in payload.notes)
    )
    if incomplete:
        raise UnprocessableError("Fill in every card, time, and note, or remove the empty ones.")
    if any(item.variant not in {"default", "primary"} for item in payload.cards):
        raise UnprocessableError("Choose a card style.")


def _match(raw: str | None, existing: dict) -> object | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _apply_cards(
    db: AsyncSession,
    block_id: uuid.UUID,
    items: list[CardWrite],
    existing: dict[uuid.UUID, ShippingBlockCard],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                ShippingBlockCard(
                    block_id=block_id,
                    icon=item.icon,
                    eyebrow=item.eyebrow,
                    title=item.title,
                    body=item.body,
                    variant=item.variant,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.icon = item.icon
        current.eyebrow = item.eyebrow
        current.title = item.title
        current.body = item.body
        current.variant = item.variant
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


def _apply_times(
    db: AsyncSession,
    block_id: uuid.UUID,
    items: list[TimeWrite],
    existing: dict[uuid.UUID, ShippingBlockTime],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                ShippingBlockTime(
                    block_id=block_id,
                    label=item.label,
                    value=item.value,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.label = item.label
        current.value = item.value
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


def _apply_notes(
    db: AsyncSession,
    block_id: uuid.UUID,
    items: list[NoteWrite],
    existing: dict[uuid.UUID, ShippingBlockNote],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                ShippingBlockNote(
                    block_id=block_id,
                    icon=item.icon,
                    title=item.title,
                    body=item.body,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.icon = item.icon
        current.title = item.title
        current.body = item.body
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


async def update_block(db: AsyncSession, payload: BlockWrite) -> BlockAdmin:
    _check(payload)
    row = await ensure_block(db)
    row.is_active = payload.is_active
    row.icon = payload.icon
    row.nav_label = payload.nav_label
    row.heading = payload.heading
    row.intro = payload.intro
    row.timelines_title = payload.timelines_title
    cards = {item.id: item for item in await _rows(db, ShippingBlockCard, row.id)}
    times = {item.id: item for item in await _rows(db, ShippingBlockTime, row.id)}
    notes = {item.id: item for item in await _rows(db, ShippingBlockNote, row.id)}
    _apply_cards(db, row.id, payload.cards, cards)
    _apply_times(db, row.id, payload.timelines, times)
    _apply_notes(db, row.id, payload.notes, notes)
    for extra in (*cards.values(), *times.values(), *notes.values()):
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(
        row,
        await _rows(db, ShippingBlockCard, row.id),
        await _rows(db, ShippingBlockTime, row.id),
        await _rows(db, ShippingBlockNote, row.id),
    )
