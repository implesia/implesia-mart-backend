import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.sustainability.impact import SustainabilityImpact, SustainabilityImpactItem
from app.schemas.sustainability.impact import (
    ImpactAdmin,
    ImpactCopyUpdate,
    ImpactItemPublic,
    ImpactItemRead,
    ImpactItemWrite,
    ImpactPublic,
    ImpactReorder,
)

SECTION_SLUG = "sustainability"
MAX_STATS = 12
DEFAULT_COPY = {
    "kicker": "আমাদের অভ্যাস",
    "title": "যা আমরা প্রতিদিন মেনে চলি",
    "subtitle": "বড় সংখ্যা নয় — যাচাই করা প্রক্রিয়া।",
}
DEFAULT_ITEMS: tuple[dict[str, object], ...] = (
    {"icon": "payments", "value": "COD", "label": "ক্যাশ অন ডেলিভারি", "sort_order": 0},
    {"icon": "assignment_return", "value": "৩ দিন", "label": "ইজি রিটার্ন", "sort_order": 1},
    {"icon": "verified", "value": "চেক", "label": "পাঠানোর আগে যাচাই", "sort_order": 2},
    {"icon": "eco", "value": "কম", "label": "প্লাস্টিক প্যাক", "sort_order": 3},
)


def present(item: SustainabilityImpactItem) -> ImpactItemRead:
    return ImpactItemRead(
        id=item.id,
        icon=item.icon,
        value=item.value,
        label=item.label,
        is_active=item.is_active,
    )


async def _items(
    db: AsyncSession, impact_id: uuid.UUID, *, active_only: bool
) -> list[SustainabilityImpactItem]:
    query = select(SustainabilityImpactItem).where(SustainabilityImpactItem.impact_id == impact_id)
    if active_only:
        query = query.where(SustainabilityImpactItem.is_active.is_(True))
    query = query.order_by(SustainabilityImpactItem.sort_order, SustainabilityImpactItem.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_impact(db: AsyncSession) -> SustainabilityImpact:
    row = await db.scalar(
        select(SustainabilityImpact).where(SustainabilityImpact.slug == SECTION_SLUG)
    )
    if row is not None:
        return row
    row = SustainabilityImpact(slug=SECTION_SLUG, **DEFAULT_COPY)
    db.add(row)
    await db.flush()
    for raw in DEFAULT_ITEMS:
        db.add(SustainabilityImpactItem(impact_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> ImpactAdmin:
    row = await ensure_impact(db)
    items = await _items(db, row.id, active_only=False)
    return ImpactAdmin(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        items=[present(item) for item in items],
    )


async def public_view(db: AsyncSession) -> ImpactPublic:
    row = await ensure_impact(db)
    items = await _items(db, row.id, active_only=True)
    return ImpactPublic(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        items=[
            ImpactItemPublic(id=item.id, icon=item.icon, value=item.value, label=item.label)
            for item in items
        ],
    )


async def update_copy(db: AsyncSession, payload: ImpactCopyUpdate) -> ImpactAdmin:
    row = await ensure_impact(db)
    row.kicker = payload.kicker
    row.title = payload.title
    row.subtitle = payload.subtitle
    await db.commit()
    return await admin_view(db)


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> SustainabilityImpactItem:
    item = await db.get(SustainabilityImpactItem, item_id)
    if item is None:
        raise NotFoundError("Stat not found")
    return item


def _require_copy(payload: ImpactItemWrite) -> None:
    if not payload.value:
        raise UnprocessableError("Value is required.")
    if not payload.label:
        raise UnprocessableError("Label is required.")


async def create_item(db: AsyncSession, payload: ImpactItemWrite) -> ImpactItemRead:
    _require_copy(payload)
    row = await ensure_impact(db)
    count = await db.scalar(
        select(func.count())
        .select_from(SustainabilityImpactItem)
        .where(SustainabilityImpactItem.impact_id == row.id)
    )
    if int(count or 0) >= MAX_STATS:
        raise UnprocessableError("You can show up to 12 stats")
    current = await db.scalar(
        select(func.max(SustainabilityImpactItem.sort_order)).where(
            SustainabilityImpactItem.impact_id == row.id
        )
    )
    item = SustainabilityImpactItem(
        impact_id=row.id,
        sort_order=0 if current is None else int(current) + 1,
        **payload.model_dump(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def update_item(
    db: AsyncSession, item: SustainabilityImpactItem, payload: ImpactItemWrite
) -> ImpactItemRead:
    _require_copy(payload)
    item.icon = payload.icon
    item.value = payload.value
    item.label = payload.label
    item.is_active = payload.is_active
    await db.commit()
    await db.refresh(item)
    return present(item)


async def delete_item(db: AsyncSession, item: SustainabilityImpactItem) -> None:
    await db.delete(item)
    await db.commit()


async def reorder(db: AsyncSession, payload: ImpactReorder) -> ImpactAdmin:
    row = await ensure_impact(db)
    items = await _items(db, row.id, active_only=False)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every stat in the new order")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return await admin_view(db)
