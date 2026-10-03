import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.home.trust import HomeTrust, HomeTrustItem
from app.schemas.home.trust import (
    TrustItemPublic,
    TrustItemRead,
    TrustItemUpdate,
    TrustItemWrite,
    TrustPublic,
    TrustReorder,
)

TRUST_SLUG = "home"
MAX_ITEMS = 12
DEFAULTS: tuple[dict[str, object], ...] = (
    {
        "icon": "payments",
        "label": "ক্যাশ অন ডেলিভারি",
        "href": "/shipping-returns",
        "sort_order": 0,
    },
    {
        "icon": "local_shipping",
        "label": "সারাদেশে ডেলিভারি",
        "href": "/shipping-returns",
        "sort_order": 1,
    },
    {
        "icon": "assignment_return",
        "label": "৩ দিন ইজি রিটার্ন",
        "href": "/shipping-returns",
        "sort_order": 2,
    },
)


def present(item: HomeTrustItem) -> TrustItemRead:
    return TrustItemRead.model_validate(item)


async def _items(
    db: AsyncSession, trust_id: uuid.UUID, *, active_only: bool
) -> list[HomeTrustItem]:
    query = select(HomeTrustItem).where(HomeTrustItem.trust_id == trust_id)
    if active_only:
        query = query.where(HomeTrustItem.is_active.is_(True))
    query = query.order_by(HomeTrustItem.sort_order, HomeTrustItem.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_trust(db: AsyncSession) -> HomeTrust:
    trust = await db.scalar(select(HomeTrust).where(HomeTrust.slug == TRUST_SLUG))
    if trust is not None:
        return trust
    trust = HomeTrust(slug=TRUST_SLUG)
    db.add(trust)
    await db.flush()
    for raw in DEFAULTS:
        db.add(HomeTrustItem(trust_id=trust.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(trust)
    return trust


async def list_items(db: AsyncSession) -> list[TrustItemRead]:
    trust = await ensure_trust(db)
    return [present(item) for item in await _items(db, trust.id, active_only=False)]


async def public_items(db: AsyncSession) -> TrustPublic:
    trust = await ensure_trust(db)
    items = await _items(db, trust.id, active_only=True)
    return TrustPublic(
        items=[
            TrustItemPublic(id=item.id, icon=item.icon, label=item.label, href=item.href)
            for item in items
        ]
    )


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> HomeTrustItem:
    item = await db.get(HomeTrustItem, item_id)
    if item is None:
        raise NotFoundError("Trust benefit not found")
    return item


async def create_item(db: AsyncSession, payload: TrustItemWrite) -> TrustItemRead:
    trust = await ensure_trust(db)
    count = await db.scalar(
        select(func.count()).select_from(HomeTrustItem).where(HomeTrustItem.trust_id == trust.id)
    )
    if int(count or 0) >= MAX_ITEMS:
        raise UnprocessableError("You can show up to 12 benefits")
    current = await db.scalar(
        select(func.max(HomeTrustItem.sort_order)).where(HomeTrustItem.trust_id == trust.id)
    )
    item = HomeTrustItem(
        trust_id=trust.id,
        sort_order=0 if current is None else int(current) + 1,
        **payload.model_dump(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def update_item(
    db: AsyncSession, item: HomeTrustItem, payload: TrustItemUpdate
) -> TrustItemRead:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def delete_item(db: AsyncSession, item: HomeTrustItem) -> None:
    await db.delete(item)
    await db.commit()


async def reorder(db: AsyncSession, payload: TrustReorder) -> list[TrustItemRead]:
    trust = await ensure_trust(db)
    items = await _items(db, trust.id, active_only=False)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every benefit in the new order")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return [present(item) for item in await _items(db, trust.id, active_only=False)]
