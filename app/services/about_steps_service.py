import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.about_steps import AboutStepItem, AboutSteps
from app.schemas.about_steps import (
    StepItemPublic,
    StepItemRead,
    StepItemWrite,
    StepReorder,
    StepsAdmin,
    StepsCopyUpdate,
    StepsPublic,
)

SECTION_SLUG = "about"
MAX_STEPS = 12
DEFAULT_COPY = {
    "kicker": "সহজ প্রক্রিয়া",
    "title": "কীভাবে অর্ডার করবেন",
    "subtitle": "চার ধাপে অর্ডার — হাতে পেয়ে তারপর পেমেন্ট।",
}
DEFAULT_ITEMS: tuple[dict[str, object], ...] = (
    {
        "step_label": "০১",
        "icon": "search",
        "title": "প্রোডাক্ট বাছাই করুন",
        "description": "পছন্দের প্রোডাক্ট খুঁজে নিন এবং কার্টে যুক্ত করুন।",
        "sort_order": 0,
    },
    {
        "step_label": "০২",
        "icon": "task_alt",
        "title": "অর্ডার কনফার্ম করুন",
        "description": "নাম, ঠিকানা ও ফোন নাম্বার দিয়ে অর্ডার কনফার্ম করুন।",
        "sort_order": 1,
    },
    {
        "step_label": "০৩",
        "icon": "local_shipping",
        "title": "সারাদেশে ডেলিভারি",
        "description": "ঢাকা থেকে দূরের জেলা — অর্ডার আপনার ঠিকানায় পৌঁছে যাবে।",
        "sort_order": 2,
    },
    {
        "step_label": "০৪",
        "icon": "payments",
        "title": "হাতে পেয়ে পেমেন্ট",
        "description": "প্রোডাক্ট দেখে, যাচাই করে তারপর ক্যাশ পেমেন্ট করুন।",
        "sort_order": 3,
    },
)


def present(item: AboutStepItem) -> StepItemRead:
    return StepItemRead(
        id=item.id,
        step=item.step_label,
        icon=item.icon,
        title=item.title,
        description=item.description,
        is_active=item.is_active,
    )


async def _items(
    db: AsyncSession, steps_id: uuid.UUID, *, active_only: bool
) -> list[AboutStepItem]:
    query = select(AboutStepItem).where(AboutStepItem.steps_id == steps_id)
    if active_only:
        query = query.where(AboutStepItem.is_active.is_(True))
    query = query.order_by(AboutStepItem.sort_order, AboutStepItem.created_at)
    result = await db.execute(query)
    return list(result.scalars().all())


async def ensure_steps(db: AsyncSession) -> AboutSteps:
    row = await db.scalar(select(AboutSteps).where(AboutSteps.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = AboutSteps(slug=SECTION_SLUG, **DEFAULT_COPY)
    db.add(row)
    await db.flush()
    for raw in DEFAULT_ITEMS:
        db.add(AboutStepItem(steps_id=row.id, is_active=True, **raw))
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> StepsAdmin:
    row = await ensure_steps(db)
    items = await _items(db, row.id, active_only=False)
    return StepsAdmin(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        items=[present(item) for item in items],
    )


async def public_view(db: AsyncSession) -> StepsPublic:
    row = await ensure_steps(db)
    items = await _items(db, row.id, active_only=True)
    return StepsPublic(
        kicker=row.kicker,
        title=row.title,
        subtitle=row.subtitle,
        items=[
            StepItemPublic(
                id=item.id,
                step=item.step_label,
                icon=item.icon,
                title=item.title,
                description=item.description,
            )
            for item in items
        ],
    )


async def update_copy(db: AsyncSession, payload: StepsCopyUpdate) -> StepsAdmin:
    row = await ensure_steps(db)
    row.kicker = payload.kicker
    row.title = payload.title
    row.subtitle = payload.subtitle
    await db.commit()
    return await admin_view(db)


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> AboutStepItem:
    item = await db.get(AboutStepItem, item_id)
    if item is None:
        raise NotFoundError("Step not found")
    return item


def _require_copy(payload: StepItemWrite) -> None:
    if not payload.step:
        raise UnprocessableError("Number is required.")
    if not payload.title:
        raise UnprocessableError("Title is required.")
    if not payload.description:
        raise UnprocessableError("Description is required.")


async def create_item(db: AsyncSession, payload: StepItemWrite) -> StepItemRead:
    _require_copy(payload)
    row = await ensure_steps(db)
    count = await db.scalar(
        select(func.count()).select_from(AboutStepItem).where(AboutStepItem.steps_id == row.id)
    )
    if int(count or 0) >= MAX_STEPS:
        raise UnprocessableError("You can show up to 12 steps")
    current = await db.scalar(
        select(func.max(AboutStepItem.sort_order)).where(AboutStepItem.steps_id == row.id)
    )
    item = AboutStepItem(
        steps_id=row.id,
        step_label=payload.step,
        icon=payload.icon,
        title=payload.title,
        description=payload.description,
        is_active=payload.is_active,
        sort_order=0 if current is None else int(current) + 1,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return present(item)


async def update_item(
    db: AsyncSession, item: AboutStepItem, payload: StepItemWrite
) -> StepItemRead:
    _require_copy(payload)
    item.step_label = payload.step
    item.icon = payload.icon
    item.title = payload.title
    item.description = payload.description
    item.is_active = payload.is_active
    await db.commit()
    await db.refresh(item)
    return present(item)


async def delete_item(db: AsyncSession, item: AboutStepItem) -> None:
    await db.delete(item)
    await db.commit()


async def reorder(db: AsyncSession, payload: StepReorder) -> StepsAdmin:
    row = await ensure_steps(db)
    items = await _items(db, row.id, active_only=False)
    current = {item.id for item in items}
    incoming = payload.ids
    if len(incoming) != len(set(incoming)) or set(incoming) != current:
        raise UnprocessableError("Send every step in the new order")
    order = {item_id: index for index, item_id in enumerate(incoming)}
    for item in items:
        item.sort_order = order[item.id]
    await db.commit()
    return await admin_view(db)
