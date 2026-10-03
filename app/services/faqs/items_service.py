import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.faqs.categories import FaqCategoryItem
from app.models.faqs.items import FaqQuestion
from app.schemas.faqs.items import (
    ItemPublic,
    ItemRead,
    ItemReorder,
    ItemsAdmin,
    ItemsPublic,
    ItemWrite,
)

MAX_ITEMS = 40


def present(item: FaqQuestion) -> ItemRead:
    return ItemRead(
        id=str(item.id),
        category_id=str(item.category_id) if item.category_id else None,
        question=item.question,
        answer=item.answer,
        is_active=item.is_active,
    )


def _public_item(item: FaqQuestion) -> ItemPublic:
    return ItemPublic(
        id=str(item.id),
        category_id=str(item.category_id) if item.category_id else None,
        question=item.question,
        answer=item.answer,
    )


async def _items(db: AsyncSession, *, active_only: bool) -> list[FaqQuestion]:
    query = select(FaqQuestion)
    if active_only:
        query = query.where(FaqQuestion.is_active.is_(True))
    query = query.order_by(FaqQuestion.sort_order, FaqQuestion.created_at)
    return list(await db.scalars(query))


async def admin_view(db: AsyncSession) -> ItemsAdmin:
    return ItemsAdmin(items=[present(item) for item in await _items(db, active_only=False)])


async def public_view(db: AsyncSession) -> ItemsPublic:
    return ItemsPublic(items=[_public_item(item) for item in await _items(db, active_only=True)])


def _check(payload: ItemWrite) -> None:
    if not payload.question:
        raise UnprocessableError("Question is required.")
    if not payload.answer:
        raise UnprocessableError("Answer is required.")


async def _category(db: AsyncSession, raw: str) -> uuid.UUID:
    try:
        key = uuid.UUID(raw)
    except ValueError as exc:
        raise UnprocessableError("Choose a category.") from exc
    row = await db.get(FaqCategoryItem, key)
    if row is None:
        raise UnprocessableError("Choose a category.")
    return key


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> FaqQuestion:
    item = await db.get(FaqQuestion, item_id)
    if item is None:
        raise NotFoundError("Question not found")
    return item


async def create_item(db: AsyncSession, payload: ItemWrite) -> ItemRead:
    _check(payload)
    category_id = await _category(db, payload.category_id)
    count = await db.scalar(select(func.count()).select_from(FaqQuestion))
    if int(count or 0) >= MAX_ITEMS:
        raise UnprocessableError("You can add up to 40 questions.")
    current = await db.scalar(select(func.max(FaqQuestion.sort_order)))
    item = FaqQuestion(
        category_id=category_id,
        question=payload.question,
        answer=payload.answer,
        is_active=payload.is_active,
        sort_order=0 if current is None else int(current) + 1,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def update_item(db: AsyncSession, item: FaqQuestion, payload: ItemWrite) -> ItemRead:
    _check(payload)
    item.category_id = await _category(db, payload.category_id)
    item.question = payload.question
    item.answer = payload.answer
    item.is_active = payload.is_active
    await db.commit()
    await db.refresh(item)
    return present(item)


async def delete_item(db: AsyncSession, item: FaqQuestion) -> None:
    await db.delete(item)
    await db.commit()


async def reorder(db: AsyncSession, payload: ItemReorder) -> ItemsAdmin:
    items = await _items(db, active_only=False)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every question in the new order.")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return await admin_view(db)
