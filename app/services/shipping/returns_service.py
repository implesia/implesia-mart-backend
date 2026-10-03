import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.shipping.returns import ShippingReturnNote, ShippingReturnRule, ShippingReturns
from app.schemas.shipping.returns import (
    NotePublic,
    NoteRead,
    NoteWrite,
    ReturnsAdmin,
    ReturnsPublic,
    ReturnsWrite,
    RulePublic,
    RuleRead,
    RuleWrite,
)

SECTION_SLUG = "returns"
MAX_ITEMS = 12
EMPTY = ReturnsPublic(
    icon="",
    nav_label="",
    heading="",
    eligibility_title="",
    eligibility_body="",
    rules=[],
    notes=[],
)


def _admin(
    row: ShippingReturns,
    rules: list[ShippingReturnRule],
    notes: list[ShippingReturnNote],
) -> ReturnsAdmin:
    return ReturnsAdmin(
        is_active=row.is_active,
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        eligibility_title=row.eligibility_title,
        eligibility_body=row.eligibility_body,
        rules=[
            RuleRead(id=str(item.id), text=item.text, is_active=item.is_active) for item in rules
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
    row: ShippingReturns,
    rules: list[ShippingReturnRule],
    notes: list[ShippingReturnNote],
) -> ReturnsPublic:
    if not row.is_active or not row.heading:
        return EMPTY
    return ReturnsPublic(
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        eligibility_title=row.eligibility_title,
        eligibility_body=row.eligibility_body,
        rules=[
            RulePublic(id=str(item.id), text=item.text) for item in rules if item.is_active
        ],
        notes=[
            NotePublic(id=str(item.id), icon=item.icon, title=item.title, body=item.body)
            for item in notes
            if item.is_active
        ],
    )


async def _rules(db: AsyncSession, returns_id: uuid.UUID) -> list[ShippingReturnRule]:
    rows = await db.scalars(
        select(ShippingReturnRule)
        .where(ShippingReturnRule.returns_id == returns_id)
        .order_by(ShippingReturnRule.sort_order, ShippingReturnRule.created_at)
    )
    return list(rows)


async def _notes(db: AsyncSession, returns_id: uuid.UUID) -> list[ShippingReturnNote]:
    rows = await db.scalars(
        select(ShippingReturnNote)
        .where(ShippingReturnNote.returns_id == returns_id)
        .order_by(ShippingReturnNote.sort_order, ShippingReturnNote.created_at)
    )
    return list(rows)


async def ensure_returns(db: AsyncSession) -> ShippingReturns:
    row = await db.scalar(select(ShippingReturns).where(ShippingReturns.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ShippingReturns(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> ReturnsAdmin:
    row = await ensure_returns(db)
    return _admin(row, await _rules(db, row.id), await _notes(db, row.id))


async def public_view(db: AsyncSession) -> ReturnsPublic:
    row = await ensure_returns(db)
    return _public(row, await _rules(db, row.id), await _notes(db, row.id))


def _check(payload: ReturnsWrite) -> None:
    if not payload.heading:
        raise UnprocessableError("Heading is required.")
    if len(payload.rules) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 rules.")
    if len(payload.notes) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 notes.")
    incomplete = any(not item.text for item in payload.rules) or any(
        not item.title for item in payload.notes
    )
    if incomplete:
        raise UnprocessableError("Fill in every rule and note, or remove the empty ones.")


def _match_rule(
    raw: str | None,
    existing: dict[uuid.UUID, ShippingReturnRule],
) -> ShippingReturnRule | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _match_note(
    raw: str | None,
    existing: dict[uuid.UUID, ShippingReturnNote],
) -> ShippingReturnNote | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _apply_rules(
    db: AsyncSession,
    returns_id: uuid.UUID,
    items: list[RuleWrite],
    existing: dict[uuid.UUID, ShippingReturnRule],
) -> None:
    for index, item in enumerate(items):
        current = _match_rule(item.id, existing)
        if current is None:
            db.add(
                ShippingReturnRule(
                    returns_id=returns_id,
                    text=item.text,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.text = item.text
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


def _apply_notes(
    db: AsyncSession,
    returns_id: uuid.UUID,
    items: list[NoteWrite],
    existing: dict[uuid.UUID, ShippingReturnNote],
) -> None:
    for index, item in enumerate(items):
        current = _match_note(item.id, existing)
        if current is None:
            db.add(
                ShippingReturnNote(
                    returns_id=returns_id,
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


async def update_returns(db: AsyncSession, payload: ReturnsWrite) -> ReturnsAdmin:
    _check(payload)
    row = await ensure_returns(db)
    row.is_active = payload.is_active
    row.icon = payload.icon
    row.nav_label = payload.nav_label
    row.heading = payload.heading
    row.eligibility_title = payload.eligibility_title
    row.eligibility_body = payload.eligibility_body
    rules = {item.id: item for item in await _rules(db, row.id)}
    notes = {item.id: item for item in await _notes(db, row.id)}
    _apply_rules(db, row.id, payload.rules, rules)
    _apply_notes(db, row.id, payload.notes, notes)
    for extra in (*rules.values(), *notes.values()):
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _rules(db, row.id), await _notes(db, row.id))
