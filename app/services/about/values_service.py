import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.about.values import AboutValueItem, AboutValues
from app.schemas.about.values import (
    ValueItemPublic,
    ValueItemRead,
    ValueItemWrite,
    ValueReorder,
    ValuesAdmin,
    ValuesCopyUpdate,
    ValuesPublic,
)

SECTION_SLUG = "about"
MAX_VALUES = 12
DEFAULT_COPY = {
    "kicker": "আমাদের মূলনীতি",
    "title": "যেভাবে আমরা কাজ করি",
    "subtitle": "প্রতিটি সিদ্ধান্তে আমরা এই চারটি মূলনীতি মেনে চলি।",
}
DEFAULT_ITEMS: tuple[dict[str, object], ...] = (
    {
        "icon": "verified",
        "title": "কোয়ালিটি চেকড",
        "description": "ডেলিভারির আগে প্রতিটি প্রোডাক্ট চালিয়ে পরীক্ষা করা হয়।",
        "sort_order": 0,
    },
    {
        "icon": "payments",
        "title": "ক্যাশ অন ডেলিভারি",
        "description": "আগে টাকা লাগবে না — হাতে পেয়ে, দেখে তারপর পেমেন্ট।",
        "sort_order": 1,
    },
    {
        "icon": "local_shipping",
        "title": "সারাদেশে ডেলিভারি",
        "description": "ঢাকা থেকে দূরের জেলা — সবখানে দ্রুত পৌঁছে যায়।",
        "sort_order": 2,
    },
    {
        "icon": "assignment_return",
        "title": "সহজ রিটার্ন",
        "description": "সমস্যা হলে ৩ দিনের মধ্যে সহজেই রিটার্ন করা যায়।",
        "sort_order": 3,
    },
)


def present(item: AboutValueItem) -> ValueItemRead:
    return ValueItemRead(
        id=item.id,
        icon=item.icon,
        title=item.title,
        description=item.description,
        is_active=item.is_active,
    )


async def _items(
    db: AsyncSession, values_id: uuid.UUID, *, active_only: bool
) -> list[AboutValueItem]:
    query = select(AboutValueItem).where(AboutValueItem.values_id == values_id)
    if active_only:
        query = query.where(AboutValueItem.is_active.is_(True))
    query = query.order_by(AboutValueItem.sort_order, AboutValueItem.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_values(db: AsyncSession) -> AboutValues:
    row = await db.scalar(select(AboutValues).where(AboutValues.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = AboutValues(slug=SECTION_SLUG, **DEFAULT_COPY)
    db.add(row)
    await db.flush()
    for raw in DEFAULT_ITEMS:
        db.add(AboutValueItem(values_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> ValuesAdmin:
    row = await ensure_values(db)
    items = await _items(db, row.id, active_only=False)
    return ValuesAdmin(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        items=[present(item) for item in items],
    )


async def public_view(db: AsyncSession) -> ValuesPublic:
    row = await ensure_values(db)
    items = await _items(db, row.id, active_only=True)
    return ValuesPublic(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        items=[
            ValueItemPublic(
                id=item.id,
                icon=item.icon,
                title=item.title,
                description=item.description,
            )
            for item in items
        ],
    )


async def update_copy(db: AsyncSession, payload: ValuesCopyUpdate) -> ValuesAdmin:
    row = await ensure_values(db)
    row.kicker = payload.kicker
    row.title = payload.title
    row.subtitle = payload.subtitle
    await db.commit()
    return await admin_view(db)


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> AboutValueItem:
    item = await db.get(AboutValueItem, item_id)
    if item is None:
        raise NotFoundError("Value not found")
    return item


def _require_copy(payload: ValueItemWrite) -> None:
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if not payload.description:
        raise UnprocessableError("Description is required.")


async def create_item(db: AsyncSession, payload: ValueItemWrite) -> ValueItemRead:
    _require_copy(payload)
    row = await ensure_values(db)
    count = await db.scalar(
        select(func.count()).select_from(AboutValueItem).where(AboutValueItem.values_id == row.id)
    )
    if int(count or 0) >= MAX_VALUES:
        raise UnprocessableError("You can show up to 12 values")
    current = await db.scalar(
        select(func.max(AboutValueItem.sort_order)).where(AboutValueItem.values_id == row.id)
    )
    item = AboutValueItem(
        values_id=row.id,
        sort_order=0 if current is None else int(current) + 1,
        **payload.model_dump(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def update_item(
    db: AsyncSession, item: AboutValueItem, payload: ValueItemWrite
) -> ValueItemRead:
    _require_copy(payload)
    item.icon = payload.icon
    item.title = payload.title
    item.description = payload.description
    item.is_active = payload.is_active
    await db.commit()
    await db.refresh(item)
    return present(item)


async def delete_item(db: AsyncSession, item: AboutValueItem) -> None:
    await db.delete(item)
    await db.commit()


async def reorder(db: AsyncSession, payload: ValueReorder) -> ValuesAdmin:
    row = await ensure_values(db)
    items = await _items(db, row.id, active_only=False)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every value in the new order")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return await admin_view(db)
