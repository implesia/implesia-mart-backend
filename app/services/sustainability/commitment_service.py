import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.sustainability.commitment import (
    SustainabilityCommitment,
    SustainabilityCommitmentItem,
)
from app.schemas.sustainability.commitment import (
    CommitmentAdmin,
    CommitmentCopyUpdate,
    CommitmentItemPublic,
    CommitmentItemRead,
    CommitmentItemWrite,
    CommitmentPublic,
    CommitmentReorder,
)

SECTION_SLUG = "sustainability"
MAX_CARDS = 12
DEFAULT_COPY = {
    "kicker": "আমাদের অঙ্গীকার",
    "title": "আমরা যেভাবে দায়িত্ব পালন করি",
    "subtitle": "প্রতিটি সিদ্ধান্তে মানুষ ও পরিবেশ — দুটোকেই মাথায় রাখি।",
}
DEFAULT_ITEMS: tuple[dict[str, object], ...] = (
    {
        "icon": "verified",
        "title": "কোয়ালিটি চেকড",
        "description": "ডেলিভারির আগে গ্যাজেট চালিয়ে, ড্রেসের ফিনিশিং দেখে যাচাই।",
        "sort_order": 0,
    },
    {
        "icon": "eco",
        "title": "কম প্লাস্টিক প্যাক",
        "description": "যতটা সম্ভব রিসাইক্লেবল ও কম প্লাস্টিক প্যাকেজিং।",
        "sort_order": 1,
    },
    {
        "icon": "volunteer_activism",
        "title": "গর্জিয়াস ড্রেস",
        "description": "হাতে তৈরি — কাস্টম মাপ ও টেকসই সেলাইয়ে।",
        "sort_order": 2,
    },
    {
        "icon": "assignment_return",
        "title": "৩ দিন রিটার্ন",
        "description": "সমস্যা হলে তিন দিনের মধ্যে সহজেই রিটার্ন।",
        "sort_order": 3,
    },
)


def present(item: SustainabilityCommitmentItem) -> CommitmentItemRead:
    return CommitmentItemRead(
        id=item.id,
        icon=item.icon,
        title=item.title,
        description=item.description,
        is_active=item.is_active,
    )


async def _items(
    db: AsyncSession, commitment_id: uuid.UUID, *, active_only: bool
) -> list[SustainabilityCommitmentItem]:
    query = select(SustainabilityCommitmentItem).where(
        SustainabilityCommitmentItem.commitment_id == commitment_id
    )
    if active_only:
        query = query.where(SustainabilityCommitmentItem.is_active.is_(True))
    query = query.order_by(
        SustainabilityCommitmentItem.sort_order, SustainabilityCommitmentItem.created_at
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_commitment(db: AsyncSession) -> SustainabilityCommitment:
    row = await db.scalar(
        select(SustainabilityCommitment).where(SustainabilityCommitment.slug == SECTION_SLUG)
    )
    if row is not None:
        return row
    row = SustainabilityCommitment(slug=SECTION_SLUG, **DEFAULT_COPY)
    db.add(row)
    await db.flush()
    for raw in DEFAULT_ITEMS:
        db.add(SustainabilityCommitmentItem(commitment_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> CommitmentAdmin:
    row = await ensure_commitment(db)
    items = await _items(db, row.id, active_only=False)
    return CommitmentAdmin(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        items=[present(item) for item in items],
    )


async def public_view(db: AsyncSession) -> CommitmentPublic:
    row = await ensure_commitment(db)
    items = await _items(db, row.id, active_only=True)
    return CommitmentPublic(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        items=[
            CommitmentItemPublic(
                id=item.id, icon=item.icon, title=item.title, description=item.description
            )
            for item in items
        ],
    )


async def update_copy(db: AsyncSession, payload: CommitmentCopyUpdate) -> CommitmentAdmin:
    row = await ensure_commitment(db)
    row.kicker = payload.kicker
    row.title = payload.title
    row.subtitle = payload.subtitle
    await db.commit()
    return await admin_view(db)


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> SustainabilityCommitmentItem:
    item = await db.get(SustainabilityCommitmentItem, item_id)
    if item is None:
        raise NotFoundError("Card not found")
    return item


def _require_copy(payload: CommitmentItemWrite) -> None:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if not payload.description:
        raise UnprocessableError("Description is required.")


async def create_item(db: AsyncSession, payload: CommitmentItemWrite) -> CommitmentItemRead:
    _require_copy(payload)
    row = await ensure_commitment(db)
    count = await db.scalar(
        select(func.count())
        .select_from(SustainabilityCommitmentItem)
        .where(SustainabilityCommitmentItem.commitment_id == row.id)
    )
    if int(count or 0) >= MAX_CARDS:
        raise UnprocessableError("You can show up to 12 cards")
    current = await db.scalar(
        select(func.max(SustainabilityCommitmentItem.sort_order)).where(
            SustainabilityCommitmentItem.commitment_id == row.id
        )
    )
    item = SustainabilityCommitmentItem(
        commitment_id=row.id,
        sort_order=0 if current is None else int(current) + 1,
        **payload.model_dump(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def update_item(
    db: AsyncSession, item: SustainabilityCommitmentItem, payload: CommitmentItemWrite
) -> CommitmentItemRead:
    _require_copy(payload)
    item.icon = payload.icon
    item.title = payload.title
    item.description = payload.description
    item.is_active = payload.is_active
    await db.commit()
    await db.refresh(item)
    return present(item)


async def delete_item(db: AsyncSession, item: SustainabilityCommitmentItem) -> None:
    await db.delete(item)
    await db.commit()


async def reorder(db: AsyncSession, payload: CommitmentReorder) -> CommitmentAdmin:
    row = await ensure_commitment(db)
    items = await _items(db, row.id, active_only=False)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every card in the new order")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return await admin_view(db)
