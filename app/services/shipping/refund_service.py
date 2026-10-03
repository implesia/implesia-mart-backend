import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.shipping.refund import ShippingRefund, ShippingRefundStep
from app.schemas.shipping.refund import (
    RefundAdmin,
    RefundPublic,
    RefundWrite,
    StepPublic,
    StepRead,
    StepWrite,
)

SECTION_SLUG = "refund"
MAX_STEPS = 12
EMPTY = RefundPublic(icon="", nav_label="", heading="", steps=[], note="")


def _admin(row: ShippingRefund, steps: list[ShippingRefundStep]) -> RefundAdmin:
    return RefundAdmin(
        is_active=row.is_active,
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        note=row.note,
        steps=[
            StepRead(id=str(item.id), title=item.title, body=item.body, is_active=item.is_active)
            for item in steps
        ],
    )


def _public(row: ShippingRefund, steps: list[ShippingRefundStep]) -> RefundPublic:
    if not row.is_active or not row.heading:
        return EMPTY
    return RefundPublic(
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        note=row.note,
        steps=[
            StepPublic(id=str(item.id), title=item.title, body=item.body)
            for item in steps
            if item.is_active
        ],
    )


async def _steps(db: AsyncSession, refund_id: uuid.UUID) -> list[ShippingRefundStep]:
    rows = await db.scalars(
        select(ShippingRefundStep)
        .where(ShippingRefundStep.refund_id == refund_id)
        .order_by(ShippingRefundStep.sort_order, ShippingRefundStep.created_at)
    )
    return list(rows)


async def ensure_refund(db: AsyncSession) -> ShippingRefund:
    row = await db.scalar(select(ShippingRefund).where(ShippingRefund.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ShippingRefund(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> RefundAdmin:
    row = await ensure_refund(db)
    return _admin(row, await _steps(db, row.id))


async def public_view(db: AsyncSession) -> RefundPublic:
    row = await ensure_refund(db)
    return _public(row, await _steps(db, row.id))


def _check(payload: RefundWrite) -> None:
    if not payload.heading:
        raise UnprocessableError("Heading is required.")
    if len(payload.steps) > MAX_STEPS:
        raise UnprocessableError("You can add up to 12 steps.")
    if any(not item.title for item in payload.steps):
        raise UnprocessableError("Every step needs a title.")


def _match(
    raw: str | None,
    existing: dict[uuid.UUID, ShippingRefundStep],
) -> ShippingRefundStep | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _apply(
    db: AsyncSession,
    refund_id: uuid.UUID,
    items: list[StepWrite],
    existing: dict[uuid.UUID, ShippingRefundStep],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                ShippingRefundStep(
                    refund_id=refund_id,
                    title=item.title,
                    body=item.body,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.title = item.title
        current.body = item.body
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


async def update_refund(db: AsyncSession, payload: RefundWrite) -> RefundAdmin:
    _check(payload)
    row = await ensure_refund(db)
    row.is_active = payload.is_active
    row.icon = payload.icon
    row.nav_label = payload.nav_label
    row.heading = payload.heading
    row.note = payload.note
    steps = {item.id: item for item in await _steps(db, row.id)}
    _apply(db, row.id, payload.steps, steps)
    for extra in steps.values():
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _steps(db, row.id))
