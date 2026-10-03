import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.shipping.faq import ShippingFaq, ShippingFaqItem
from app.schemas.shipping.faq import FaqAdmin, FaqPublic, FaqWrite, ItemPublic, ItemRead, ItemWrite
from app.services.contact.hero_service import _safe_href

SECTION_SLUG = "faq"
MAX_ITEMS = 12
EMPTY = FaqPublic(
    title="",
    items=[],
    more_before="",
    more_link_label="",
    more_href="",
    more_after="",
)


def _admin(row: ShippingFaq, items: list[ShippingFaqItem]) -> FaqAdmin:
    return FaqAdmin(
        is_active=row.is_active,
        title=row.title,
        more_before=row.more_before,
        more_link_label=row.more_link_label,
        more_href=row.more_href,
        more_after=row.more_after,
        items=[
            ItemRead(
                id=str(item.id),
                question=item.question,
                answer=item.answer,
                is_active=item.is_active,
            )
            for item in items
        ],
    )


def _visible(row: ShippingFaq, items: list[ShippingFaqItem]) -> bool:
    questions = [item for item in items if item.is_active and item.question and item.answer]
    more = row.more_before or row.more_link_label or row.more_after
    return bool(row.is_active and (questions or more))


def _public(row: ShippingFaq, items: list[ShippingFaqItem]) -> FaqPublic:
    if not _visible(row, items):
        return EMPTY
    return FaqPublic(
        title=row.title,
        more_before=row.more_before,
        more_link_label=row.more_link_label,
        more_href=row.more_href,
        more_after=row.more_after,
        items=[
            ItemPublic(id=str(item.id), question=item.question, answer=item.answer)
            for item in items
            if item.is_active and item.question and item.answer
        ],
    )


async def _items(db: AsyncSession, faq_id: uuid.UUID) -> list[ShippingFaqItem]:
    rows = await db.scalars(
        select(ShippingFaqItem)
        .where(ShippingFaqItem.faq_id == faq_id)
        .order_by(ShippingFaqItem.sort_order, ShippingFaqItem.created_at)
    )
    return list(rows)


async def ensure_faq(db: AsyncSession) -> ShippingFaq:
    row = await db.scalar(select(ShippingFaq).where(ShippingFaq.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ShippingFaq(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> FaqAdmin:
    row = await ensure_faq(db)
    return _admin(row, await _items(db, row.id))


async def public_view(db: AsyncSession) -> FaqPublic:
    row = await ensure_faq(db)
    return _public(row, await _items(db, row.id))


def _check(payload: FaqWrite) -> None:
    if len(payload.items) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 questions.")
    if any(not item.question or not item.answer for item in payload.items):
        raise UnprocessableError("Every question needs a question and an answer.")
    _safe_href(payload.more_href)


def _match(
    raw: str | None,
    existing: dict[uuid.UUID, ShippingFaqItem],
) -> ShippingFaqItem | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _apply(
    db: AsyncSession,
    faq_id: uuid.UUID,
    items: list[ItemWrite],
    existing: dict[uuid.UUID, ShippingFaqItem],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                ShippingFaqItem(
                    faq_id=faq_id,
                    question=item.question,
                    answer=item.answer,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.question = item.question
        current.answer = item.answer
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


async def update_faq(db: AsyncSession, payload: FaqWrite) -> FaqAdmin:
    _check(payload)
    row = await ensure_faq(db)
    row.is_active = payload.is_active
    row.title = payload.title
    row.more_before = payload.more_before
    row.more_link_label = payload.more_link_label
    row.more_href = payload.more_href
    row.more_after = payload.more_after
    stored = {item.id: item for item in await _items(db, row.id)}
    _apply(db, row.id, payload.items, stored)
    for extra in stored.values():
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _items(db, row.id))
