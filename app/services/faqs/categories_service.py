import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.faqs.categories import FaqCategories, FaqCategoryItem
from app.schemas.faqs.categories import (
    CategoriesAdmin,
    CategoriesPublic,
    CategoriesWrite,
    ItemPublic,
    ItemRead,
)

SECTION_SLUG = "faqs"
MAX_ITEMS = 12
EMPTY = CategoriesPublic(
    title="",
    subtitle="",
    all_label="",
    all_icon="",
    nav_label="",
    items=[],
)


def _admin(row: FaqCategories, items: list[FaqCategoryItem]) -> CategoriesAdmin:
    return CategoriesAdmin(
        is_active=row.is_active,
        title=row.title,
        subtitle=row.subtitle,
        all_label=row.all_label,
        all_icon=row.all_icon,
        nav_label=row.nav_label,
        items=[
            ItemRead(id=str(item.id), label=item.label, icon=item.icon, is_active=item.is_active)
            for item in items
        ],
    )


def _has_copy(row: FaqCategories, items: list[FaqCategoryItem]) -> bool:
    return bool(
        row.title
        or row.subtitle
        or row.all_label
        or row.all_icon
        or row.nav_label
        or any(item.is_active for item in items)
    )


def _public(row: FaqCategories, items: list[FaqCategoryItem]) -> CategoriesPublic:
    visible = [item for item in items if item.is_active]
    if not row.is_active or not _has_copy(row, visible):
        return EMPTY
    return CategoriesPublic(
        title=row.title,
        subtitle=row.subtitle,
        all_label=row.all_label,
        all_icon=row.all_icon,
        nav_label=row.nav_label,
        items=[ItemPublic(id=str(item.id), label=item.label, icon=item.icon) for item in visible],
    )


async def _items(db: AsyncSession, categories_id: object) -> list[FaqCategoryItem]:
    rows = await db.scalars(
        select(FaqCategoryItem)
        .where(FaqCategoryItem.categories_id == categories_id)
        .order_by(FaqCategoryItem.sort_order, FaqCategoryItem.created_at)
    )
    return list(rows)


async def ensure_categories(db: AsyncSession) -> FaqCategories:
    row = await db.scalar(select(FaqCategories).where(FaqCategories.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = FaqCategories(slug=SECTION_SLUG, is_active=True)
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


def _match(raw: str | None, existing: dict[uuid.UUID, FaqCategoryItem]) -> FaqCategoryItem | None:
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
    row.title = payload.title
    row.subtitle = payload.subtitle
    row.all_label = payload.all_label
    row.all_icon = payload.all_icon
    row.nav_label = payload.nav_label
    existing = {item.id: item for item in await _items(db, row.id)}
    for index, item in enumerate(payload.items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                FaqCategoryItem(
                    categories_id=row.id,
                    label=item.label,
                    icon=item.icon,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.label = item.label
        current.icon = item.icon
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)
    for extra in existing.values():
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _items(db, row.id))
