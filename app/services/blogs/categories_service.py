import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.blogs.categories import BlogCategories, BlogCategoryItem
from app.schemas.blogs.categories import (
    CategoriesAdmin,
    CategoriesPublic,
    CategoriesWrite,
    ItemPublic,
    ItemRead,
)

SECTION_SLUG = "blogs"
MAX_ITEMS = 12
EMPTY = CategoriesPublic(items=[])


def _admin(row: BlogCategories, items: list[BlogCategoryItem]) -> CategoriesAdmin:
    return CategoriesAdmin(
        is_active=row.is_active,
        items=[
            ItemRead(id=str(item.id), label=item.label, is_active=item.is_active) for item in items
        ],
    )


def _public(row: BlogCategories, items: list[BlogCategoryItem]) -> CategoriesPublic:
    if not row.is_active:
        return EMPTY
    return CategoriesPublic(
        items=[ItemPublic(id=str(item.id), label=item.label) for item in items if item.is_active]
    )


async def _items(db: AsyncSession, categories_id: object) -> list[BlogCategoryItem]:
    rows = await db.scalars(
        select(BlogCategoryItem)
        .where(BlogCategoryItem.categories_id == categories_id)
        .order_by(BlogCategoryItem.sort_order, BlogCategoryItem.created_at)
    )
    return list(rows)


async def ensure_categories(db: AsyncSession) -> BlogCategories:
    row = await db.scalar(select(BlogCategories).where(BlogCategories.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = BlogCategories(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> CategoriesAdmin:
    row = await ensure_categories(db)
    return _admin(row, await _items(db, row.id))


async def public_view(db: AsyncSession) -> CategoriesPublic:
    row = await ensure_categories(db)
    return _public(row, await _items(db, row.id))


def _check(payload: CategoriesWrite) -> None:
    if len(payload.items) > MAX_ITEMS:
        raise UnprocessableError("You can add up to 12 categories.")
    if any(not item.label for item in payload.items):
        raise UnprocessableError("Every category needs a name.")
    labels = [item.label for item in payload.items]
    if len(labels) != len(set(labels)):
        raise UnprocessableError("Each category name can only be used once.")


def _match(raw: str | None, existing: dict[uuid.UUID, BlogCategoryItem]) -> BlogCategoryItem | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


async def update_categories(db: AsyncSession, payload: CategoriesWrite) -> CategoriesAdmin:
    _check(payload)
    row = await ensure_categories(db)
    row.is_active = payload.is_active
    existing = {item.id: item for item in await _items(db, row.id)}
    for index, item in enumerate(payload.items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                BlogCategoryItem(
                    categories_id=row.id,
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
    for extra in existing.values():
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _items(db, row.id))
