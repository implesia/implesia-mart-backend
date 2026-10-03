from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.contact.faq import ContactFaq, ContactFaqItem
from app.schemas.contact.faq import FaqAdmin, FaqPublic, FaqWrite, ItemPublic, ItemRead

SECTION_SLUG = "contact"
MAX_ITEMS = 12
EMPTY = FaqPublic(title="", subtitle="", items=[])


def _admin(row: ContactFaq, items: list[ContactFaqItem]) -> FaqAdmin:
    return FaqAdmin(
        is_active=row.is_active,
        title=row.title,
        subtitle=row.subtitle,
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


def _public(row: ContactFaq, items: list[ContactFaqItem]) -> FaqPublic:
    if not row.is_active or not row.title:
        return EMPTY
    return FaqPublic(
        title=row.title,
        subtitle=row.subtitle,
        items=[
            ItemPublic(id=str(item.id), question=item.question, answer=item.answer)
            for item in items
            if item.is_active
        ],
    )


async def _items(db: AsyncSession, faq_id: object) -> list[ContactFaqItem]:
    rows = await db.scalars(
        select(ContactFaqItem)
        .where(ContactFaqItem.faq_id == faq_id)
        .order_by(ContactFaqItem.sort_order, ContactFaqItem.created_at)
    )
    return list(rows)


async def ensure_faq(db: AsyncSession) -> ContactFaq:
    row = await db.scalar(select(ContactFaq).where(ContactFaq.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ContactFaq(slug=SECTION_SLUG, is_active=True)
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
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if len(payload.items) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 questions.")
    if any(not item.question or not item.answer for item in payload.items):
        raise UnprocessableError("Each question needs a question and an answer.")


async def update_faq(db: AsyncSession, payload: FaqWrite) -> FaqAdmin:
    _check(payload)
    row = await ensure_faq(db)
    row.is_active = payload.is_active
    row.title = payload.title
    row.subtitle = payload.subtitle
    existing = await _items(db, row.id)
    for index, item in enumerate(payload.items):
        if index < len(existing):
            current = existing[index]
            current.question = item.question
            current.answer = item.answer
            current.is_active = item.is_active
            current.sort_order = index
        else:
            db.add(
                ContactFaqItem(
                    faq_id=row.id,
                    question=item.question,
                    answer=item.answer,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
    for extra in existing[len(payload.items) :]:
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _items(db, row.id))
