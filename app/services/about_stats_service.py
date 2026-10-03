import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.about_stats import AboutStatItem, AboutStats
from app.schemas.about_stats import (
    StatItemPublic,
    StatItemRead,
    StatItemUpdate,
    StatItemWrite,
    StatReorder,
    StatsPublic,
)

STATS_SLUG = "about"
MAX_STATS = 12
DEFAULTS: tuple[dict[str, object], ...] = (
    {"icon": "category", "value": "২", "label": "ক্যাটাগরি", "sort_order": 0},
    {"icon": "location_on", "value": "৬৪", "label": "জেলায় ডেলিভারি", "sort_order": 1},
    {"icon": "payments", "value": "COD", "label": "ক্যাশ অন ডেলিভারি", "sort_order": 2},
    {"icon": "assignment_return", "value": "৩ দিন", "label": "ইজি রিটার্ন", "sort_order": 3},
)


def present(item: AboutStatItem) -> StatItemRead:
    return StatItemRead.model_validate(item)


async def _items(
    db: AsyncSession, stats_id: uuid.UUID, *, active_only: bool
) -> list[AboutStatItem]:
    query = select(AboutStatItem).where(AboutStatItem.stats_id == stats_id)
    if active_only:
        query = query.where(AboutStatItem.is_active.is_(True))
    query = query.order_by(AboutStatItem.sort_order, AboutStatItem.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_stats(db: AsyncSession) -> AboutStats:
    row = await db.scalar(select(AboutStats).where(AboutStats.slug == STATS_SLUG))
    if row is not None:
        return row
    row = AboutStats(slug=STATS_SLUG)
    db.add(row)
    await db.flush()
    for raw in DEFAULTS:
        db.add(AboutStatItem(stats_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def list_items(db: AsyncSession) -> list[StatItemRead]:
    row = await ensure_stats(db)
    return [present(item) for item in await _items(db, row.id, active_only=False)]


async def public_items(db: AsyncSession) -> StatsPublic:
    row = await ensure_stats(db)
    items = await _items(db, row.id, active_only=True)
    return StatsPublic(
        items=[
            StatItemPublic(
                id=item.id,
                icon=item.icon,  # type: ignore[arg-type]
                value=item.value,
                label=item.label,
            )
            for item in items
        ]
    )


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> AboutStatItem:
    item = await db.get(AboutStatItem, item_id)
    if item is None:
        raise NotFoundError("Stat not found")
    return item


async def create_item(db: AsyncSession, payload: StatItemWrite) -> StatItemRead:
    row = await ensure_stats(db)
    count = await db.scalar(
        select(func.count()).select_from(AboutStatItem).where(AboutStatItem.stats_id == row.id)
    )
    if int(count or 0) >= MAX_STATS:
        raise UnprocessableError("You can show up to 12 stats")
    current = await db.scalar(
        select(func.max(AboutStatItem.sort_order)).where(AboutStatItem.stats_id == row.id)
    )
    item = AboutStatItem(
        stats_id=row.id,
        sort_order=0 if current is None else int(current) + 1,
        **payload.model_dump(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def update_item(
    db: AsyncSession, item: AboutStatItem, payload: StatItemUpdate
) -> StatItemRead:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def delete_item(db: AsyncSession, item: AboutStatItem) -> None:
    await db.delete(item)
    await db.commit()


async def reorder(db: AsyncSession, payload: StatReorder) -> list[StatItemRead]:
    row = await ensure_stats(db)
    items = await _items(db, row.id, active_only=False)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every stat in the new order")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return [present(item) for item in await _items(db, row.id, active_only=False)]
