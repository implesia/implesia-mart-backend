import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.shipping.payment import ShippingPayment, ShippingPaymentCard
from app.schemas.shipping.payment import (
    CardPublic,
    CardRead,
    CardWrite,
    PaymentAdmin,
    PaymentPublic,
    PaymentWrite,
)

SECTION_SLUG = "payment"
MAX_CARDS = 12
EMPTY = PaymentPublic(icon="", nav_label="", heading="", intro="", cards=[])


def _admin(row: ShippingPayment, cards: list[ShippingPaymentCard]) -> PaymentAdmin:
    return PaymentAdmin(
        is_active=row.is_active,
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        intro=row.intro,
        cards=[
            CardRead(
                id=str(item.id),
                icon=item.icon,
                badge=item.badge,
                title=item.title,
                body=item.body,
                footnote=item.footnote,
                is_active=item.is_active,
            )
            for item in cards
        ],
    )


def _public(row: ShippingPayment, cards: list[ShippingPaymentCard]) -> PaymentPublic:
    if not row.is_active or not row.heading:
        return EMPTY
    return PaymentPublic(
        icon=row.icon,
        nav_label=row.nav_label,
        heading=row.heading,
        intro=row.intro,
        cards=[
            CardPublic(
                id=str(item.id),
                icon=item.icon,
                badge=item.badge,
                title=item.title,
                body=item.body,
                footnote=item.footnote,
            )
            for item in cards
            if item.is_active
        ],
    )


async def _cards(db: AsyncSession, payment_id: uuid.UUID) -> list[ShippingPaymentCard]:
    rows = await db.scalars(
        select(ShippingPaymentCard)
        .where(ShippingPaymentCard.payment_id == payment_id)
        .order_by(ShippingPaymentCard.sort_order, ShippingPaymentCard.created_at)
    )
    return list(rows)


async def ensure_payment(db: AsyncSession) -> ShippingPayment:
    row = await db.scalar(select(ShippingPayment).where(ShippingPayment.slug == SECTION_SLUG))
    if row is not None:
        return row
    row = ShippingPayment(slug=SECTION_SLUG, is_active=True)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def admin_view(db: AsyncSession) -> PaymentAdmin:
    row = await ensure_payment(db)
    return _admin(row, await _cards(db, row.id))


async def public_view(db: AsyncSession) -> PaymentPublic:
    row = await ensure_payment(db)
    return _public(row, await _cards(db, row.id))


def _check(payload: PaymentWrite) -> None:
    if not payload.heading:
        raise UnprocessableError("Heading is required.")
    if len(payload.cards) > MAX_CARDS:
        raise UnprocessableError("You can add up to 12 cards.")
    if any(not item.title for item in payload.cards):
        raise UnprocessableError("Every card needs a title.")


def _match(
    raw: str | None,
    existing: dict[uuid.UUID, ShippingPaymentCard],
) -> ShippingPaymentCard | None:
    if not raw:
        return None
    try:
        key = uuid.UUID(raw)
    except ValueError:
        return None
    return existing.get(key)


def _apply(
    db: AsyncSession,
    payment_id: uuid.UUID,
    items: list[CardWrite],
    existing: dict[uuid.UUID, ShippingPaymentCard],
) -> None:
    for index, item in enumerate(items):
        current = _match(item.id, existing)
        if current is None:
            db.add(
                ShippingPaymentCard(
                    payment_id=payment_id,
                    icon=item.icon,
                    badge=item.badge,
                    title=item.title,
                    body=item.body,
                    footnote=item.footnote,
                    is_active=item.is_active,
                    sort_order=index,
                )
            )
            continue
        current.icon = item.icon
        current.badge = item.badge
        current.title = item.title
        current.body = item.body
        current.footnote = item.footnote
        current.is_active = item.is_active
        current.sort_order = index
        existing.pop(current.id, None)


async def update_payment(db: AsyncSession, payload: PaymentWrite) -> PaymentAdmin:
    _check(payload)
    row = await ensure_payment(db)
    row.is_active = payload.is_active
    row.icon = payload.icon
    row.nav_label = payload.nav_label
    row.heading = payload.heading
    row.intro = payload.intro
    cards = {item.id: item for item in await _cards(db, row.id)}
    _apply(db, row.id, payload.cards, cards)
    for extra in cards.values():
        await db.delete(extra)
    await db.commit()
    await db.refresh(row)
    return _admin(row, await _cards(db, row.id))
