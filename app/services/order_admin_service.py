"""Staff order desk: offline entry, overview, bulk moves, pack slips, item edits.

Online checkout stays in order_service. This module calls that path for stock,
totals, coupons, and status changes so the two entry points cannot drift.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTasks

from app.core.config import settings
from app.core.exceptions import AppError, ConflictError, NotFoundError, UnprocessableError
from app.models.audit_event import AuditAction
from app.models.coupon import Coupon, CouponRedemption
from app.models.inventory import MovementType, StockMovement
from app.models.notification import CustomerNotification
from app.models.order import (
    OFFLINE_CHANNEL,
    ActivityAction,
    Order,
    OrderActivity,
    OrderIdempotency,
    OrderItem,
    OrderOrigin,
    OrderSource,
    OrderStatus,
)
from app.models.product import Product, ProductVariant, StockStatus
from app.models.review import ProductReview
from app.models.user import User
from app.schemas.inquiry import normalize_phone
from app.schemas.order import (
    _MONEY_CAP,
    AdminOrderLineInput,
    AdminOrderList,
    AdminOrderQuery,
    BulkStatusItem,
    BulkStatusRequest,
    BulkStatusResult,
    CustomerMatch,
    CustomerSearch,
    OfflineOrderCreate,
    OrderDeleteImpact,
    OrderDeleteRequest,
    OrderDeleteResult,
    OrderItemsUpdate,
    OrderOverview,
    OrderPaymentCreate,
    OrderRead,
    OrderStockRestoreItem,
    OriginSplit,
    OverviewOrder,
    PeriodTotals,
    PrintData,
    PrintedResult,
    PrintLine,
    PrintOrder,
    StatusCounts,
)
from app.services import (
    audit_service,
    customer_notify,
    delivery_service,
    inventory_service,
    notification_service,
    order_service,
    pricing_service,
    telegram_notify,
    variant_service,
)
from app.services.product_options import resolve_selection, selection_of, variant_label
from app.services.product_service import content_of
from app.services.shop_sql import SHOP, at_or_after, before, dialect_name

_NOT_REVENUE = (OrderStatus.CANCELLED.value, OrderStatus.RETURNED.value)
_TWOPLACES = Decimal("0.01")


class _Wanted:
    def __init__(
        self,
        product: Product,
        variant: ProductVariant | None,
        quantity: int,
        unit_price: int | None,
        selection: list[dict],
    ) -> None:
        self.product = product
        self.variant = variant
        self.quantity = quantity
        self.unit_price = unit_price
        self.selection = selection

    @property
    def key(self) -> tuple[uuid.UUID, uuid.UUID | None]:
        variant_id = self.variant.id if self.variant is not None else None
        return (self.product.id, variant_id)


def _staff_actor(user: User) -> str:
    return f"staff:{user.id}"


def _placed_column() -> Any:
    return func.coalesce(Order.ordered_at, Order.created_at)


def _percent(part: int, whole: int) -> Decimal | None:
    if whole <= 0:
        return None
    return (Decimal(part) * Decimal(100) / Decimal(whole)).quantize(
        _TWOPLACES, rounding=ROUND_HALF_UP
    )


def _charged(catalog: pricing_service.Line, unit_price: int | None) -> pricing_service.Line:
    """Catalog price, or the staff unit price with line_total = price × quantity."""
    if unit_price is None:
        return catalog
    line_total = unit_price * catalog.quantity
    if line_total > _MONEY_CAP:
        raise UnprocessableError("Line total is too large")
    return pricing_service.Line(
        regular_price=catalog.regular_price,
        base_percent=catalog.base_percent,
        quantity_percent=Decimal("0.00"),
        total_percent=catalog.base_percent,
        unit_price=unit_price,
        quantity=catalog.quantity,
        line_total=line_total,
    )


def _money(subtotal: int, coupon: int, manual: int, shipping: int) -> int:
    if coupon + manual > subtotal:
        raise UnprocessableError("Discount is larger than the merchandise total")
    total = subtotal - coupon - manual + shipping
    if total > _MONEY_CAP:
        raise UnprocessableError("Order total is too large")
    return total


def _merge_lines(items: list[AdminOrderLineInput]) -> list[AdminOrderLineInput]:
    merged: dict[tuple[uuid.UUID, uuid.UUID | None], AdminOrderLineInput] = {}
    for item in items:
        key = (item.product_id, item.variant_id)
        current = merged.get(key)
        if current is None:
            merged[key] = item.model_copy()
            continue
        if (
            current.unit_price is not None
            and item.unit_price is not None
            and current.unit_price != item.unit_price
        ):
            raise UnprocessableError("Two lines for the same product must use the same unit price")
        price = current.unit_price if current.unit_price is not None else item.unit_price
        quantity = current.quantity + item.quantity
        if quantity > _MONEY_CAP:
            raise UnprocessableError("Quantity is too large")
        merged[key] = current.model_copy(update={"quantity": quantity, "unit_price": price})
    return list(merged.values())


async def _resolve_line(db: AsyncSession, item: AdminOrderLineInput, *, existing: bool) -> _Wanted:
    product = await db.get(Product, item.product_id)
    if product is None:
        if existing:
            raise UnprocessableError("A product on this order was removed")
        raise NotFoundError("Product not found")
    if not product.published and not existing:
        raise NotFoundError("Product not found")
    variant = await variant_service.resolve_for_purchase(db, product, item.variant_id)
    if variant is not None:
        picked = variant_service.selection_of_variant(content_of(product), variant.options)
    else:
        picked = resolve_selection(content_of(product), item.selection)
    return _Wanted(
        product,
        variant,
        item.quantity,
        item.unit_price,
        [option.model_dump() for option in picked],
    )


def _append_item(
    order: Order,
    wanted: _Wanted,
    line: pricing_service.Line,
    unit_cost: Decimal | None,
) -> None:
    variant = wanted.variant
    order.items.append(
        OrderItem(
            product_id=wanted.product.id,
            variant_id=variant.id if variant is not None else None,
            sku=variant.sku if variant is not None else "",
            title=wanted.product.title,
            slug=wanted.product.slug,
            image_src=wanted.product.image_src,
            unit_price=line.unit_price,
            quantity=line.quantity,
            line_total=line.line_total,
            selection=wanted.selection,
            regular_price=line.regular_price,
            base_discount=pricing_service.to_hundredths(line.base_percent),
            quantity_discount=pricing_service.to_hundredths(line.quantity_percent),
            total_discount=pricing_service.to_hundredths(line.total_percent),
            unit_cost=unit_cost,
        )
    )


async def _claim_lines(
    db: AsyncSession, lines: list[_Wanted], rules: pricing_service.Rules
) -> list[tuple[_Wanted, pricing_service.Line]]:
    priced: list[tuple[_Wanted, pricing_service.Line]] = []
    ordered = sorted(lines, key=lambda row: (row.key[0].hex, str(row.key[1] or "")))
    for wanted in ordered:
        catalog, _title, _slug, _image, _sku_text = await order_service._claim(
            db, wanted.product, wanted.variant, wanted.quantity, rules
        )
        priced.append((wanted, _charged(catalog, wanted.unit_price)))
    return priced


def _order_date(day: date | None) -> datetime:
    if day is None:
        return datetime.now(UTC)
    today = datetime.now(SHOP).date()
    if day > today or day.year < 2020:
        raise UnprocessableError("Order date must be from 2020 through today in Asia/Dhaka")
    return datetime.combine(day, time.min, tzinfo=SHOP)


async def create_offline(
    db: AsyncSession,
    payload: OfflineOrderCreate,
    *,
    actor: User,
    idempotency_key: str,
    background: BackgroundTasks | None = None,
) -> OrderRead:
    """A counter order. Stock and totals follow checkout. No customer or ad events."""
    key = order_service.require_idempotency_key(idempotency_key)
    staff = _staff_actor(actor)
    replayed = await order_service._replay(db, staff, key)
    if replayed is not None:
        return await order_service.present(db, replayed, with_activity=True)
    telegram_notify.discard_low_stock(db)
    inventory_service.clear_pending_sales(db)

    wanted = [await _resolve_line(db, item, existing=False) for item in _merge_lines(payload.items)]
    rates = await delivery_service.fees(db)
    zone, fee, available = delivery_service.price_for(payload.district, payload.area, None, rates)
    if payload.delivery_charge is None:
        if not available:
            raise UnprocessableError("Delivery is not available for this area")
        shipping = fee
    else:
        shipping = payload.delivery_charge

    rules = await pricing_service.store_rules(db)
    priced = await _claim_lines(db, wanted, rules)
    subtotal = sum(line.line_total for _wanted, line in priced)
    total = _money(subtotal, 0, payload.manual_discount, shipping)
    if payload.paid_amount > total:
        raise UnprocessableError("Paid amount cannot be larger than the order total")
    due = total - payload.paid_amount

    # Link to an existing registered customer when the phone matches (same rule as online checkout).
    user_id: uuid.UUID | None = None
    if payload.phone:
        from app.services.customer_auth_service import normalize_bd_phone

        norm_phone = normalize_bd_phone(payload.phone)
        if norm_phone:
            user_id = await db.scalar(select(User.id).where(User.phone == norm_phone))

    ordered_at = _order_date(payload.order_date)
    initial_status = payload.initial_status
    delivered_at = ordered_at if initial_status == OrderStatus.DELIVERED.value else None

    order = Order(
        number=await order_service._number(db),
        user_id=user_id,
        source=OrderSource.DIRECT.value,
        origin=OrderOrigin.OFFLINE.value,
        channel=OFFLINE_CHANNEL,
        status=initial_status,
        payment_method=payload.payment_method,
        advance_percent=None,
        advance_amount=payload.paid_amount,
        due_amount=due,
        paid_amount=payload.paid_amount,
        payment_reference=payload.payment_reference,
        customer_name=payload.customer_name,
        phone=payload.phone,
        email=payload.email,
        district=payload.district,
        area=payload.area,
        address=payload.address,
        notes=payload.notes,
        delivery_zone=zone,
        subtotal=subtotal,
        shipping=shipping,
        manual_discount=payload.manual_discount,
        total=total,
        ordered_at=ordered_at,
        delivered_at=delivered_at,
        inventory_held=True,
    )
    for wanted_line, line in priced:
        _append_item(
            order,
            wanted_line,
            line,
            variant_service.effective_unit_cost(wanted_line.product, wanted_line.variant),
        )
    db.add(order)
    await db.flush()
    order_service.log_activity(
        db,
        order.id,
        actor.id,
        ActivityAction.CREATED,
        "Offline order entered",
        {"origin": OrderOrigin.OFFLINE.value, "initial_status": initial_status},
    )
    if initial_status != OrderStatus.NEW.value:
        order_service.log_activity(
            db,
            order.id,
            actor.id,
            ActivityAction.STATUS_CHANGED,
            f"Status new to {initial_status}",
            {"from": OrderStatus.NEW.value, "to": initial_status},
        )
    inventory_service.attach_pending_sales(db, order.id)
    db.add(OrderIdempotency(actor=staff, idempotency_key=key, order_id=order.id))
    order_id = order.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        telegram_notify.discard_low_stock(db)
        replayed = await order_service._replay(db, staff, key)
        if replayed is not None:
            return await order_service.present(db, replayed, with_activity=True)
        raise ConflictError("Could not place the order. Try again.") from None
    db.expire_all()
    # Counter sales do not email, Telegram the shopper, or send Meta Purchase.
    # A low-stock note can still fire: that is an inventory alert, not an order alert.
    telegram_notify.flush_low_stock(db, background)
    loaded = await order_service._load(db, order_id)
    return await order_service.present(db, loaded, with_activity=True)


async def replace_items(
    db: AsyncSession,
    order_id: uuid.UUID,
    payload: OrderItemsUpdate,
    *,
    actor: User,
    background: BackgroundTasks | None = None,
) -> OrderRead:
    """Replace lines while the order is still new. Stock and totals move with the edit."""
    telegram_notify.discard_low_stock(db)
    inventory_service.clear_pending_sales(db)
    order = await order_service._load(db, order_id)
    if order.status != OrderStatus.NEW.value:
        raise UnprocessableError("Items can be edited only while the order is new")
    if not order.inventory_held:
        raise UnprocessableError("Stock for this order is no longer held")
    if any(item.product_id is None for item in order.items):
        raise UnprocessableError("A product on this order was removed")

    before = [
        {"title": item.title, "quantity": item.quantity, "unit_price": item.unit_price}
        for item in order.items
    ]
    old_qty: dict[tuple[uuid.UUID, uuid.UUID | None], int] = {}
    for item in order.items:
        if item.product_id is None:
            continue
        key = (item.product_id, item.variant_id)
        old_qty[key] = old_qty.get(key, 0) + item.quantity

    wanted_rows: list[_Wanted] = []
    for incoming in _merge_lines(payload.items):
        line_key = (incoming.product_id, incoming.variant_id)
        wanted_rows.append(await _resolve_line(db, incoming, existing=line_key in old_qty))
    wanted = {row.key: row for row in wanted_rows}
    old_cost = {
        (item.product_id, item.variant_id): item.unit_cost
        for item in order.items
        if item.product_id is not None
    }
    rules = await pricing_service.store_rules(db)
    keys = sorted(set(old_qty) | set(wanted), key=lambda key: (key[0].hex, str(key[1] or "")))
    for key in keys:
        previous = old_qty.get(key, 0)
        row = wanted.get(key)
        target = row.quantity if row is not None else 0
        delta = target - previous
        product = row.product if row is not None else await db.get(Product, key[0])
        if product is None:
            raise UnprocessableError("A product on this order was removed")
        variant = row.variant if row is not None else None
        if delta < 0 and key[1] is None and product.has_variants:
            raise UnprocessableError("A product on this order was removed")
        if delta > 0:
            await order_service._claim(
                db,
                product,
                variant,
                delta,
                rules,
                enforce_limits=previous == 0,
            )
        elif delta < 0:
            await order_service.release_units(
                db,
                product_id=product.id,
                variant_id=key[1],
                quantity=-delta,
                order_id=order.id,
                actor_id=actor.id,
                movement_type=MovementType.CANCEL.value,
                note="order item edit",
            )
        if row is not None:
            minimum, maximum = variant_service.order_limits(product, rules.max_quantity)
            if target > maximum:
                raise UnprocessableError(variant_service.over_limit_message(maximum))
            if target < minimum:
                raise UnprocessableError(f"The minimum order for this product is {minimum}")

    order.items.clear()
    subtotal = 0
    for row in wanted.values():
        catalog = pricing_service.price_product(row.product, row.variant, row.quantity, rules)
        line = _charged(catalog, row.unit_price)
        subtotal += line.line_total
        _append_item(
            order,
            row,
            line,
            old_cost.get(
                row.key,
                variant_service.effective_unit_cost(row.product, row.variant),
            ),
        )
    coupon = order.coupon_discount or 0
    manual = order.manual_discount if payload.manual_discount is None else payload.manual_discount
    shipping = order.shipping if payload.delivery_charge is None else payload.delivery_charge
    total = _money(subtotal, coupon, manual, shipping)
    paid = order_service.effective_paid(order)
    if paid > total:
        raise UnprocessableError("Paid amount is larger than the new total")
    order.subtotal = subtotal
    order.manual_discount = manual
    order.shipping = shipping
    order.total = total
    order.due_amount = total - paid
    order_service.log_activity(
        db,
        order.id,
        actor.id,
        ActivityAction.ITEMS_EDITED,
        "Items updated",
        {
            "before": before,
            "after": [
                {"title": item.title, "quantity": item.quantity, "unit_price": item.unit_price}
                for item in order.items
            ],
        },
    )
    inventory_service.attach_pending_sales(db, order.id)
    kept = order.id
    await db.commit()
    db.expire_all()
    telegram_notify.flush_low_stock(db, background)
    return await order_service.present(db, await order_service._load(db, kept), with_activity=True)


async def record_payment(
    db: AsyncSession,
    order_id: uuid.UUID,
    payload: OrderPaymentCreate,
    *,
    actor: User,
) -> OrderRead:
    """Collect an additional payment against a due/partial order and log an activity entry."""
    order = await order_service._load(db, order_id)
    if order.status in _NOT_REVENUE:
        raise UnprocessableError("Cannot record a payment on a cancelled or returned order")
    before_paid = order_service.effective_paid(order)
    new_paid = before_paid + payload.amount
    if new_paid > order.total:
        raise UnprocessableError("Paid amount cannot be larger than the order total")
    order.paid_amount = new_paid
    order.due_amount = order.total - new_paid
    if payload.payment_reference:
        order.payment_reference = payload.payment_reference
    order_service.log_activity(
        db,
        order.id,
        actor.id,
        ActivityAction.PAYMENT_UPDATED,
        f"Payment recorded: {payload.amount} BDT ({new_paid}/{order.total})",
        {
            "added": payload.amount,
            "from_paid": before_paid,
            "to_paid": new_paid,
            "due_amount": order.due_amount,
            "payment_method": payload.payment_method or order.payment_method,
            "payment_reference": payload.payment_reference or order.payment_reference or "",
            "note": payload.note,
        },
    )
    kept = order.id
    await db.commit()
    db.expire_all()
    return await order_service.present(db, await order_service._load(db, kept), with_activity=True)


async def bulk_status(
    db: AsyncSession,
    payload: BulkStatusRequest,
    *,
    actor: User,
    background: BackgroundTasks | None = None,
) -> BulkStatusResult:
    """Each id is its own savepoint. One illegal move does not undo the others."""
    telegram_notify.discard_low_stock(db)
    results: list[BulkStatusItem] = []
    notify: list[uuid.UUID] = []
    sms_ids: list[uuid.UUID] = []
    changed_ids: list[uuid.UUID] = []
    target = payload.status.value
    for order_id in payload.ids:
        try:
            async with db.begin_nested():
                try:
                    order = await order_service._load(db, order_id)
                except NotFoundError:
                    results.append(BulkStatusItem(id=order_id, ok=False, error="Order not found"))
                    continue
                if order.status == target:
                    results.append(BulkStatusItem(id=order_id, ok=True, status=order.status))
                    continue
                became_cancelled = await order_service.change_status(
                    db, order, target, actor_id=actor.id
                )
                changed_ids.append(order.id)
                if became_cancelled and order.origin != OrderOrigin.OFFLINE.value:
                    notify.append(order.id)
                if target in customer_notify.SEND_ON:
                    sms_ids.append(order.id)
                results.append(BulkStatusItem(id=order_id, ok=True, status=target))
        except AppError as exc:
            results.append(BulkStatusItem(id=order_id, ok=False, status=None, error=exc.message))
    await db.commit()
    db.expire_all()
    for order_id in notify:
        telegram_notify.schedule_cancelled(background, await order_service._load(db, order_id))
    for order_id in sms_ids:
        await customer_notify.schedule(
            db, background, await order_service._load(db, order_id), target
        )
    telegram_notify.flush_low_stock(db, background)
    if payload.notify_customer:
        for order_id in changed_ids:
            await notification_service.create_order_status_notification(
                db,
                await order_service._load(db, order_id),
                target,
                language=payload.notification_language,
            )
    return BulkStatusResult(results=results)


async def mark_printed(db: AsyncSession, ids: list[uuid.UUID], *, actor: User) -> PrintedResult:
    now = datetime.now(UTC)
    printed: list[uuid.UUID] = []
    missing: list[uuid.UUID] = []
    for order_id in ids:
        order = await db.get(Order, order_id)
        if order is None:
            missing.append(order_id)
            continue
        order.printed_at = now
        order_service.log_activity(
            db,
            order.id,
            actor.id,
            ActivityAction.PRINTED,
            "Invoice printed",
            {},
        )
        printed.append(order.id)
    await db.commit()
    return PrintedResult(printed=printed, missing=missing)


def invoice_id_for(number: str) -> str:
    """Stable invoice id derived from the order number. No separate sequence.

    ``IM-AB12CD34`` becomes ``INV-AB12CD34``. A number without that prefix
    still gets a stable ``INV-`` form.
    """
    body = number[3:] if number.startswith("IM-") and len(number) > 3 else number
    return f"INV-{body}"


def full_address_of(order: Order) -> str:
    parts = [order.address.strip(), order.area.strip(), order.district.strip()]
    return ", ".join(part for part in parts if part)


def estimated_delivery_date(order: Order) -> date:
    """Order date in Asia/Dhaka plus the zone's day count.

    ``ordered_at`` wins when it is set (offline orders). Otherwise
    ``created_at``. Inside Dhaka and Dhaka-suburban share one count.
    Outside Dhaka uses the other. Nothing is written back to the order.
    """
    stamp = order.ordered_at or order.created_at
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    placed = stamp.astimezone(SHOP).date()
    days = (
        settings.delivery_days_outside_dhaka
        if order.delivery_zone == "outside"
        else settings.delivery_days_inside_dhaka
    )
    return placed + timedelta(days=days)


def short_product_id(product_id: uuid.UUID | None) -> str:
    """First 8 hex characters of the product UUID. Empty when the product is gone."""
    if product_id is None:
        return ""
    return product_id.hex[:8]


def _print_line(item: OrderItem) -> PrintLine:
    return PrintLine(
        title=item.title,
        variant_label=variant_label(item.selection),
        sku=item.sku,
        product_id_short=short_product_id(item.product_id),
        quantity=item.quantity,
        unit_price=item.unit_price,
        line_total=item.line_total,
        selection=selection_of(item.selection),
    )


async def print_data(db: AsyncSession, ids: list[uuid.UUID]) -> PrintData:
    rows = list(
        (
            await db.execute(
                select(Order).where(Order.id.in_(ids)).options(order_service._ORDER_LOAD)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    by_id = {row.id: row for row in rows}
    orders: list[PrintOrder] = []
    missing: list[uuid.UUID] = []
    for order_id in ids:
        order = by_id.get(order_id)
        if order is None:
            missing.append(order_id)
            continue
        paid = order_service.effective_paid(order)
        origin = order.origin if order.origin in {"online", "offline"} else "online"
        orders.append(
            PrintOrder(
                id=order.id,
                invoice_id=invoice_id_for(order.number),
                number=order.number,
                order_number=order.number,
                status=order.status,
                origin=origin,
                ordered_at=order.ordered_at,
                created_at=order_service._as_utc(order.created_at),
                estimated_delivery_date=estimated_delivery_date(order),
                customer_name=order.customer_name,
                phone=order.phone,
                email=order.email or "",
                district=order.district,
                area=order.area,
                address=order.address,
                full_address=full_address_of(order),
                notes=order.notes,
                courier_name=order.courier_name,
                tracking_number=order.tracking_number,
                payment_method=order.payment_method,
                payment_status=order_service.payment_status_of(paid, order.total),
                subtotal=order.subtotal,
                manual_discount=order.manual_discount,
                coupon_discount=order.coupon_discount,
                shipping=order.shipping,
                total=order.total,
                paid_amount=paid,
                due_amount=(
                    order.due_amount if order.due_amount is not None else max(order.total - paid, 0)
                ),
                items=[_print_line(item) for item in order.items],
            )
        )
    return PrintData(orders=orders, missing=missing)


async def ready_to_pack(db: AsyncSession, query: AdminOrderQuery) -> AdminOrderList:
    """Confirmed orders. Confirming an order is what puts it in this queue."""
    scoped = query.model_copy(update={"status": OrderStatus.CONFIRMED, "scope": "all"})
    return await order_service.list_orders(db, scoped)


async def _period(db: AsyncSession, start: datetime, end: datetime, dialect: str) -> PeriodTotals:
    placed = _placed_column()
    sale = Order.status.notin_(_NOT_REVENUE)
    count, revenue = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((sale, Order.total), else_=0)), 0),
            ).where(at_or_after(placed, start, dialect), before(placed, end, dialect))
        )
    ).one()
    return PeriodTotals(orders=int(count), revenue=int(revenue))


async def overview(db: AsyncSession) -> OrderOverview:
    dialect = dialect_name(db)
    now = datetime.now(SHOP)
    today = datetime.combine(now.date(), time.min, tzinfo=SHOP)
    tomorrow = today + timedelta(days=1)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    counted = (await db.execute(select(Order.status, func.count()).group_by(Order.status))).all()
    counts = {status.value: 0 for status in OrderStatus}
    for status, count in counted:
        counts[str(status)] = int(count)
    total = sum(counts.values())
    delivered = counts[OrderStatus.DELIVERED.value]
    returned = counts[OrderStatus.RETURNED.value]
    cancelled = counts[OrderStatus.CANCELLED.value]
    origin_rows = (
        await db.execute(
            select(
                Order.origin,
                func.count(),
                func.coalesce(
                    func.sum(case((Order.status.notin_(_NOT_REVENUE), Order.total), else_=0)),
                    0,
                ),
            ).group_by(Order.origin)
        )
    ).all()
    by_origin = {str(origin): (int(count), int(revenue)) for origin, count, revenue in origin_rows}
    recent_rows = list(
        (
            await db.execute(
                select(Order).order_by(Order.created_at.desc(), Order.id.desc()).limit(8)
            )
        )
        .scalars()
        .all()
    )
    return OrderOverview(
        today=await _period(db, today, tomorrow, dialect),
        week=await _period(db, week, tomorrow, dialect),
        month=await _period(db, month, tomorrow, dialect),
        pending_confirm=counts[OrderStatus.NEW.value],
        ready_to_pack=counts[OrderStatus.CONFIRMED.value],
        shipped=counts[OrderStatus.SHIPPED.value],
        return_rate_percent=_percent(returned, delivered + returned),
        cancel_rate_percent=_percent(cancelled, total),
        origins=[
            OriginSplit(
                origin=name,
                orders=by_origin.get(name, (0, 0))[0],
                revenue=by_origin.get(name, (0, 0))[1],
            )
            for name in ("online", "offline")
        ],
        status_counts=StatusCounts(**counts),
        recent=[
            OverviewOrder(
                id=row.id,
                number=row.number,
                status=row.status,
                origin=row.origin if row.origin in {"online", "offline"} else "online",
                total=row.total,
                customer_name=row.customer_name,
                phone=row.phone,
                created_at=order_service._as_utc(row.created_at),
                ordered_at=row.ordered_at,
            )
            for row in recent_rows
        ],
    )


async def search_customers(db: AsyncSession, q: str) -> CustomerSearch:
    pattern = order_service._like(q)
    phone = normalize_phone(q)
    match = or_(
        func.lower(Order.customer_name).like(pattern, escape="\\"),
        func.lower(Order.phone).like(pattern, escape="\\"),
    )
    if phone is not None:
        match = or_(match, Order.phone == phone)
    ranked = (
        select(
            Order.phone.label("phone"),
            Order.customer_name.label("customer_name"),
            Order.email.label("email"),
            Order.district.label("district"),
            Order.area.label("area"),
            Order.address.label("address"),
            Order.created_at.label("created_at"),
            func.row_number()
            .over(partition_by=Order.phone, order_by=Order.created_at.desc())
            .label("rn"),
            func.count().over(partition_by=Order.phone).label("orders"),
        )
        .where(match)
        .subquery()
    )
    rows = (
        await db.execute(
            select(ranked).where(ranked.c.rn == 1).order_by(ranked.c.created_at.desc()).limit(20)
        )
    ).all()
    return CustomerSearch(
        items=[
            CustomerMatch(
                phone=row.phone,
                customer_name=row.customer_name,
                email=row.email or "",
                district=row.district,
                area=row.area,
                address=row.address,
                orders=int(row.orders),
                last_ordered_at=order_service._as_utc(row.created_at),
            )
            for row in rows
        ]
    )


async def delete_impact(db: AsyncSession, order_id: uuid.UUID) -> OrderDeleteImpact:
    order = await order_service._load(db, order_id)
    effective_paid = (
        order.paid_amount
        if order.paid_amount > 0
        else (order.advance_amount if order.payment_method == "bangla_qr" else 0)
    )
    effective_due = (
        order.due_amount if order.due_amount is not None else max(order.total - effective_paid, 0)
    )
    restore_items = (
        [
            OrderStockRestoreItem(
                product_id=item.product_id,
                variant_id=item.variant_id,
                title=item.title,
                quantity=item.quantity,
            )
            for item in order.items
            if item.product_id is not None
        ]
        if order.inventory_held
        else []
    )
    stock_movements_count = int(
        await db.scalar(
            select(func.count())
            .select_from(StockMovement)
            .where(StockMovement.order_id == order.id)
        )
        or 0
    )
    coupon_code = await db.scalar(
        select(Coupon.code)
        .join(CouponRedemption, CouponRedemption.coupon_id == Coupon.id)
        .where(CouponRedemption.order_id == order.id)
        .limit(1)
    )
    reviews_count = int(
        await db.scalar(
            select(func.count())
            .select_from(ProductReview)
            .where(ProductReview.order_id == order.id)
        )
        or 0
    )
    notifications_count = int(
        await db.scalar(
            select(func.count())
            .select_from(CustomerNotification)
            .where(CustomerNotification.order_id == order.id)
        )
        or 0
    )
    if order.delivered_at is not None and order.status != OrderStatus.RETURNED.value:
        warning = (
            "Deleting this delivered order will permanently remove its revenue, COGS, and profit "
            "from Sales, Profit & Loss, Channel, and Supplier reports."
        )
    elif order.status == OrderStatus.RETURNED.value:
        warning = (
            "Deleting this returned order will remove it from Delivery & Return reports. "
            "Stock was already restored on return."
        )
    elif effective_paid > 0:
        warning = (
            "Deleting this order will remove recorded payment history and order totals from "
            "operational summaries."
        )
    else:
        warning = (
            "Deleting this order will permanently remove it from order history and release any "
            "held stock or coupon redemption."
        )
    return OrderDeleteImpact(
        order_number=order.number,
        status=order.status,
        origin=order.origin if order.origin in {"online", "offline"} else "online",
        total=order.total,
        paid_amount=effective_paid,
        due_amount=effective_due,
        inventory_held=order.inventory_held,
        stock_restore_items=restore_items,
        stock_movements_count=stock_movements_count,
        coupon_redemption_code=str(coupon_code) if coupon_code is not None else None,
        reviews_count=reviews_count,
        notifications_count=notifications_count,
        report_impact_warning=warning,
    )


async def _reconcile_order_stock_for_delete(
    db: AsyncSession,
    order: Order,
    *,
    reason: str,
    actor_id: uuid.UUID,
) -> int:
    """Restore held stock and insert offsetting adjustment rows so ledger == physical stock."""
    if not order.inventory_held:
        return 0
    order.inventory_held = False
    product_ids = sorted({item.product_id for item in order.items if item.product_id is not None})
    for pid in product_ids:
        await variant_service.lock_product(db, pid)
    note = f"Reconciled stock from deleted order #{order.number}: {reason}"[:500]
    restored_units = 0
    for item in order.items:
        if item.product_id is None or item.quantity <= 0:
            continue
        if item.variant_id is not None:
            variant_row = await db.get(ProductVariant, item.variant_id, populate_existing=True)
            if variant_row is None or variant_row.quantity is None:
                continue
            await variant_service.release_stock(db, variant_row.id, item.quantity)
            await variant_service.rollup_by_id(db, item.product_id)
            product = await db.get(Product, item.product_id)
            unit_cost = (
                item.unit_cost
                if item.unit_cost is not None
                else (
                    variant_service.effective_unit_cost(product, variant_row)
                    if product is not None
                    else variant_row.cost_price
                )
            )
            inventory_service.add_movement(
                db,
                product_id=item.product_id,
                variant_id=item.variant_id,
                quantity=item.quantity,
                movement_type=MovementType.ADJUSTMENT.value,
                unit_cost=unit_cost,
                order_id=None,
                actor_id=actor_id,
                note=note,
            )
            restored_units += item.quantity
            continue
        product = await db.get(Product, item.product_id, populate_existing=True)
        if product is None or product.has_variants or product.quantity is None:
            continue
        await db.execute(
            update(Product)
            .where(Product.id == product.id, Product.quantity.is_not(None))
            .values(quantity=Product.quantity + item.quantity)
        )
        await db.execute(
            update(Product)
            .where(Product.id == product.id)
            .where(Product.status == StockStatus.SOLD_OUT.value)
            .where(Product.quantity > 0)
            .values(status=StockStatus.AVAILABLE.value)
        )
        unit_cost = item.unit_cost if item.unit_cost is not None else product.cost_price
        inventory_service.add_movement(
            db,
            product_id=product.id,
            variant_id=None,
            quantity=item.quantity,
            movement_type=MovementType.ADJUSTMENT.value,
            unit_cost=unit_cost,
            order_id=None,
            actor_id=actor_id,
            note=note,
        )
        restored_units += item.quantity
    return restored_units


async def delete_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    payload: OrderDeleteRequest,
    *,
    actor: User,
) -> OrderDeleteResult:
    if not payload.confirm:
        raise UnprocessableError("Set confirm=true to delete this order")
    order = (
        await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.items))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found")

    order_number = order.number
    redemption_id = await db.scalar(
        select(CouponRedemption.id).where(CouponRedemption.order_id == order.id).limit(1)
    )
    coupon_released = redemption_id is not None

    stock_restored_units = 0
    if order.inventory_held and payload.reconcile_stock:
        stock_restored_units = await _reconcile_order_stock_for_delete(
            db, order, reason=payload.reason, actor_id=actor.id
        )

    total_cost = sum(
        ((item.unit_cost * item.quantity) for item in order.items if item.unit_cost is not None),
        Decimal("0.00"),
    )
    items_snapshot = [
        {
            "product_id": str(item.product_id) if item.product_id else None,
            "variant_id": str(item.variant_id) if item.variant_id else None,
            "title": item.title,
            "sku": item.sku,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "line_total": item.line_total,
            "unit_cost": str(item.unit_cost) if item.unit_cost is not None else None,
        }
        for item in order.items
    ]
    audit_meta = {
        "order_number": order_number,
        "status": order.status,
        "origin": order.origin,
        "channel": order.channel,
        "customer_name": order.customer_name,
        "phone": order.phone,
        "subtotal": order.subtotal,
        "shipping": order.shipping,
        "coupon_code": order.coupon_code,
        "coupon_discount": order.coupon_discount,
        "manual_discount": order.manual_discount,
        "total": order.total,
        "paid_amount": order.paid_amount,
        "due_amount": order.due_amount,
        "total_cost": str(total_cost),
        "items": items_snapshot,
        "reason": payload.reason,
        "reconcile_stock": payload.reconcile_stock,
        "stock_restored_units": stock_restored_units,
        "coupon_released": coupon_released,
    }

    # Preserve historical movements, reviews, and notifications with order_id = NULL,
    # and clean up cascade children explicitly so SQLite & PostgreSQL match identically.
    await db.execute(
        update(StockMovement).where(StockMovement.order_id == order.id).values(order_id=None)
    )
    await db.execute(
        update(ProductReview).where(ProductReview.order_id == order.id).values(order_id=None)
    )
    await db.execute(
        update(CustomerNotification)
        .where(CustomerNotification.order_id == order.id)
        .values(order_id=None)
    )
    await db.execute(delete(CouponRedemption).where(CouponRedemption.order_id == order.id))
    await db.execute(delete(OrderIdempotency).where(OrderIdempotency.order_id == order.id))
    await db.execute(delete(OrderActivity).where(OrderActivity.order_id == order.id))
    await db.delete(order)
    await audit_service.record(
        db,
        actor_id=actor.id,
        action=AuditAction.ORDER_DELETED.value,
        target_type="order",
        target_id=order_id,
        metadata=audit_meta,
    )
    await db.commit()
    return OrderDeleteResult(
        deleted_order_number=order_number,
        stock_restored_units=stock_restored_units,
        coupon_released=coupon_released,
        reports_synced=True,
    )
