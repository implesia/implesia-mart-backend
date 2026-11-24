import hmac
import re
import secrets
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import Select, and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTasks

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.audit_event import AuditAction
from app.models.inventory import MovementType
from app.models.order import (
    ORDER_TRANSITIONS,
    PAYMENT_METHODS,
    WEBSITE_CHANNEL,
    ActivityAction,
    Order,
    OrderActivity,
    OrderIdempotency,
    OrderItem,
    OrderOrigin,
    OrderStatus,
    next_statuses,
)
from app.models.product import Product, ProductVariant, StockStatus
from app.models.user import User
from app.schemas.order import (
    AdminOrderList,
    AdminOrderMetrics,
    AdminOrderQuery,
    CustomerHistory,
    NewOrderFeed,
    NewOrderItem,
    NewOrderQuery,
    OrderActivityRead,
    OrderCreate,
    OrderItemRead,
    OrderLookup,
    OrderQuoteRequest,
    OrderRead,
    OrderUpdate,
    PublicOrderItemRead,
    PublicOrderRead,
    PublicTimelineEvent,
    QuoteLineRead,
    QuoteRead,
    StatusCounts,
    order_page_count,
    purchase_event_id,
)
from app.schemas.pricing import QUANTITY_CEILING
from app.services import (
    audit_service,
    coupon_service,
    customer_notify,
    delivery_service,
    inventory_service,
    meta_capi,
    notification_service,
    payment_service,
    pricing_service,
    telegram_notify,
    variant_service,
)
from app.services.cart_service import Shopper, _cap, _purchasable, open_cart, shopper_actor
from app.services.product_options import resolve_selection, selection_of, variant_label
from app.services.product_service import content_of
from app.services.realtime_hub import STAFF_ORDERS_CHANNEL, realtime_hub
from app.services.shop_sql import SHOP, at_or_after, before, dialect_name

_KEY = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_ORDER_LOAD = selectinload(Order.items)
_RESTOCK = {OrderStatus.CANCELLED.value, OrderStatus.RETURNED.value}
# Absent `since` on the new-order feed looks back this far, not the whole table.
_NEW_ORDER_WINDOW = timedelta(hours=24)


def require_idempotency_key(value: str) -> str:
    key = value.strip()
    if not _KEY.fullmatch(key):
        raise UnprocessableError("Idempotency-Key must be 8 to 80 letters, numbers, _ or -")
    return key


class Requested(NamedTuple):
    product_id: uuid.UUID
    quantity: int
    cart_item_id: uuid.UUID | None
    selection: list[dict]
    variant_id: uuid.UUID | None = None


def _selection_key(selection: list[dict]) -> str:
    return "|".join(f"{row.get('name')}={row.get('label')}" for row in selection)


def _merge(items: list[Requested]) -> list[Requested]:
    merged: dict[tuple[uuid.UUID, uuid.UUID | None, str], Requested] = {}
    for item in items:
        key = (item.product_id, item.variant_id, _selection_key(item.selection))
        previous = merged.get(key)
        if previous is None:
            merged[key] = item
        else:
            merged[key] = item._replace(quantity=previous.quantity + item.quantity)
    for item in merged.values():
        # Per-product limits are checked when the line is priced or claimed.
        if item.quantity > QUANTITY_CEILING:
            raise UnprocessableError(variant_service.over_limit_message(QUANTITY_CEILING))
    return list(merged.values())


def _snapshot(item: OrderItem) -> dict[str, Any]:
    """The discount snapshot taken when the order was placed (None on older orders)."""

    def pct(value: int | None) -> Any:
        return None if value is None else pricing_service.from_hundredths(value)

    return {
        "regular_price": item.regular_price,
        "base_discount_percent": pct(item.base_discount),
        "quantity_discount_percent": pct(item.quantity_discount),
        "total_discount_percent": pct(item.total_discount),
    }


def effective_paid(order: Order) -> int:
    """Taka already collected. Older Bangla QR rows stored the advance and left paid_amount 0."""
    if order.paid_amount:
        return int(order.paid_amount)
    if order.payment_method == "bangla_qr":
        return int(order.advance_amount or 0)
    return 0


def payment_status_of(paid: int, total: int) -> str:
    if paid <= 0:
        return "unpaid"
    if paid >= total:
        return "paid"
    return "partial"


def _payment(order: Order) -> dict[str, Any]:
    """Payment fields for a response. Older orders (no due recorded) owe the whole total."""
    method = order.payment_method if order.payment_method in PAYMENT_METHODS else "cod"
    advance = order.advance_amount or 0
    due = order.due_amount if order.due_amount is not None else max(order.total - advance, 0)
    return {
        "payment_method": method,
        "advance_percent": order.advance_percent,
        "advance_amount": advance,
        "due_amount": due,
    }


def log_activity(
    db: AsyncSession,
    order_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    summary: str,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        OrderActivity(
            order_id=order_id,
            actor_user_id=actor_id,
            action=action,
            summary=summary[:200],
            detail=detail or {},
        )
    )


def _read(
    order: Order,
    *,
    history: CustomerHistory | None = None,
    duplicate: bool = False,
    activity: list[OrderActivityRead] | None = None,
) -> OrderRead:
    paid = effective_paid(order)
    return OrderRead(
        id=order.id,
        number=order.number,
        source=order.source,
        origin=order.origin if order.origin in {"online", "offline"} else "online",
        status=order.status,
        call_status=order.call_status,
        payment_status=payment_status_of(paid, order.total),
        **_payment(order),
        payment_reference=order.payment_reference or "",
        anonymous=order.user_id is None,
        customer_name=order.customer_name,
        phone=order.phone,
        email=order.email,
        district=order.district,
        area=order.area,
        address=order.address,
        notes=order.notes,
        delivery_zone=order.delivery_zone,
        subtotal=order.subtotal,
        shipping=order.shipping,
        total=order.total,
        coupon_code=order.coupon_code,
        coupon_discount=order.coupon_discount,
        manual_discount=order.manual_discount,
        paid_amount=paid,
        courier_name=order.courier_name,
        tracking_number=order.tracking_number,
        printed_at=order.printed_at,
        ordered_at=order.ordered_at,
        customer_history=history or CustomerHistory(phone=order.phone),
        duplicate_warning=duplicate,
        activity=activity or [],
        delivered_at=order.delivered_at,
        returned_at=order.returned_at,
        items=[
            OrderItemRead(
                id=item.id,
                product_id=item.product_id,
                variant_id=item.variant_id,
                sku=item.sku,
                title=item.title,
                slug=item.slug,
                image_src=item.image_src,
                unit_price=item.unit_price,
                quantity=item.quantity,
                line_total=item.line_total,
                selection=selection_of(item.selection),
                **_snapshot(item),
            )
            for item in order.items
        ],
        created_at=order.created_at,
        next_statuses=next_statuses(order.status),
        order_number=order.number,
        analytics_event_id=purchase_event_id(order.number),
    )


async def _load(db: AsyncSession, order_id: uuid.UUID) -> Order:
    order = (
        await db.execute(select(Order).options(_ORDER_LOAD).where(Order.id == order_id))
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found")
    return order


async def _requested(
    db: AsyncSession, shopper: Shopper, payload: OrderQuoteRequest
) -> list[Requested]:
    if payload.source == "direct":
        lines: list[Requested] = []
        for item in payload.items:
            product = await _product(db, item.product_id)
            variant = await variant_service.resolve_for_purchase(db, product, item.variant_id)
            if variant is not None:
                picked = variant_service.selection_of_variant(content_of(product), variant.options)
            else:
                picked = resolve_selection(content_of(product), item.selection)
            chosen = [option.model_dump() for option in picked]
            lines.append(
                Requested(
                    item.product_id,
                    item.quantity,
                    None,
                    chosen,
                    variant.id if variant is not None else None,
                )
            )
        return _merge(lines)

    cart = await open_cart(db, shopper)
    if cart is None or not cart.items:
        return []
    return [
        Requested(
            item.product_id,
            item.quantity,
            item.id,
            [option.model_dump() for option in selection_of(item.selection)],
            item.variant_id,
        )
        for item in cart.items
    ]


async def _variant_row(db: AsyncSession, variant_id: uuid.UUID | None) -> ProductVariant | None:
    return await db.get(ProductVariant, variant_id) if variant_id is not None else None


async def _product(db: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await db.get(Product, product_id)
    if product is None or not product.published:
        raise NotFoundError("Product not found")
    return product


def _line(
    product: Product,
    variant: ProductVariant | None,
    quantity: int,
    cart_item_id: uuid.UUID | None,
    selection: list[dict],
    rules: pricing_service.Rules,
) -> QuoteLineRead:
    limit = rules.max_quantity
    available = _purchasable(product, variant, limit)
    cap = _cap(product, variant, limit) if available else 0
    minimum = variant_service.order_limits(product, limit)[0]
    line = pricing_service.price_product(product, variant, quantity, rules)
    unit_price = line.unit_price
    counted = available and max(1, minimum) <= quantity <= max(cap, 0)
    return QuoteLineRead(
        product_id=product.id,
        variant_id=variant.id if variant is not None else None,
        sku=variant.sku if variant is not None else "",
        cart_item_id=cart_item_id,
        title=product.title,
        slug=product.slug,
        image_src=product.image_src,
        unit_price=unit_price,
        quantity=quantity,
        line_total=line.line_total if counted else 0,
        available=counted,
        max_quantity=cap,
        selection=selection_of(selection),
        regular_price=line.regular_price,
        base_discount_percent=line.base_percent,
        quantity_discount_percent=line.quantity_percent,
        total_discount_percent=line.total_percent,
    )


def _totals(
    lines: list[QuoteLineRead],
    district: str,
    area: str,
    declared: str | None,
    rates: delivery_service.StoreFees,
) -> QuoteRead:
    subtotal = sum(line.line_total for line in lines if line.available)
    count = sum(line.quantity for line in lines if line.available)
    zone, fee, available = delivery_service.price_for(district, area, declared, rates)
    shipping = fee if count and available else 0
    return QuoteRead(
        items=lines,
        item_count=count,
        subtotal=subtotal,
        shipping=shipping,
        total=subtotal + shipping,
        delivery_zone=zone,
        delivery_available=available,
    )


async def quote(db: AsyncSession, shopper: Shopper, payload: OrderQuoteRequest) -> QuoteRead:
    requested = await _requested(db, shopper, payload)
    rules = await pricing_service.store_rules(db)
    lines = [
        _line(
            await _product(db, row.product_id),
            await _variant_row(db, row.variant_id),
            row.quantity,
            row.cart_item_id,
            row.selection,
            rules,
        )
        for row in requested
    ]
    rates = await delivery_service.fees(db)
    totals = _totals(lines, payload.district, payload.area, payload.delivery_zone, rates)
    totals.coupon = await coupon_service.preview(
        db, payload.coupon_code, lines, phone=payload.phone
    )
    if totals.coupon is not None and totals.coupon.valid:
        if totals.coupon.free_delivery:
            totals.shipping = 0
        totals.total = totals.subtotal - totals.coupon.discount + totals.shipping
    if totals.total > 0 and await payment_service.bangla_qr_src(db) is not None:
        totals.bangla_qr_options = payment_service.advance_options(totals.total)
    return totals


async def _claim(
    db: AsyncSession,
    product: Product,
    variant: ProductVariant | None,
    quantity: int,
    rules: pricing_service.Rules,
    *,
    enforce_limits: bool = True,
) -> tuple[pricing_service.Line, str, str, str, str]:
    """Take stock in one conditional update. The line is priced from the locked row."""
    minimum, maximum = variant_service.order_limits(product, rules.max_quantity)
    if enforce_limits and quantity > maximum:
        raise UnprocessableError(variant_service.over_limit_message(maximum))
    if enforce_limits and quantity < minimum:
        raise UnprocessableError(f"The minimum order for this product is {minimum}")
    if variant is not None:
        return await _claim_variant(db, product, variant, quantity, rules)
    if product.has_variants:
        raise UnprocessableError("Choose an option before ordering")
    unlimited = product.quantity is None
    stmt = (
        update(Product)
        .where(Product.id == product.id)
        .where(Product.published.is_(True))
        .where(Product.status == StockStatus.AVAILABLE.value)
        .where(or_(Product.quantity.is_(None), Product.quantity >= quantity))
    )
    if unlimited:
        stmt = stmt.values(updated_at=func.now())
    else:
        stmt = stmt.values(quantity=Product.quantity - quantity)
    row = (
        await db.execute(
            stmt.returning(
                Product.price,
                Product.title,
                Product.slug,
                Product.image_src,
                Product.quantity,
                Product.compare_at_price,
                Product.base_discount,
            )
        )
    ).one_or_none()
    if row is None:
        if product.quantity is not None and 0 < product.quantity < quantity:
            raise UnprocessableError(variant_service.NOT_ENOUGH_STOCK)
        raise UnprocessableError("This product cannot be ordered")
    price, title, slug, image_src, left, compare_at, base = row
    if not unlimited and left is not None:
        telegram_notify.note_low_stock(
            db,
            product_id=product.id,
            title=str(title),
            before=int(left) + quantity,
            after=int(left),
        )
    if not unlimited:
        inventory_service.stage_sale(
            db,
            product_id=product.id,
            variant_id=None,
            quantity=-quantity,
            unit_cost=product.cost_price,
        )
    if left == 0:
        await db.execute(
            update(Product)
            .where(Product.id == product.id, Product.quantity == 0)
            .values(status=StockStatus.SOLD_OUT.value)
        )
    line = pricing_service.price_line(
        regular=pricing_service.regular_of(int(price), compare_at),
        price=int(price),
        stored_base=base,
        quantity=quantity,
        tiers=pricing_service.product_tiers(product, rules),
        rules=rules,
    )
    return line, str(title), str(slug), str(image_src), ""


async def _claim_variant(
    db: AsyncSession,
    product: Product,
    variant: ProductVariant,
    quantity: int,
    rules: pricing_service.Rules,
) -> tuple[pricing_service.Line, str, str, str, str]:
    """Same rule as a plain product, on the variant row (price and stock live there)."""
    # Lock order is product then variants everywhere (admin save, claim, restock).
    await variant_service.lock_product(db, product.id)
    live = (
        select(Product.id)
        .where(
            Product.id == product.id,
            Product.published.is_(True),
            Product.status == StockStatus.AVAILABLE.value,
        )
        .exists()
    )
    stmt = (
        update(ProductVariant)
        .where(ProductVariant.id == variant.id, ProductVariant.product_id == product.id)
        .where(ProductVariant.is_active.is_(True))
        .where(or_(ProductVariant.quantity.is_(None), ProductVariant.quantity >= quantity))
        .where(live)
    )
    if variant.quantity is None:
        stmt = stmt.values(updated_at=func.now())
    else:
        stmt = stmt.values(quantity=ProductVariant.quantity - quantity)
    row = (
        await db.execute(
            stmt.returning(
                ProductVariant.price, ProductVariant.sku, ProductVariant.compare_at_price
            )
        )
    ).one_or_none()
    if row is None:
        if variant.quantity is not None and 0 < variant.quantity < quantity:
            raise UnprocessableError(variant_service.NOT_ENOUGH_STOCK)
        raise UnprocessableError("This product cannot be ordered")
    before_qty = product.quantity
    await variant_service.rollup_by_id(db, product.id)
    telegram_notify.note_low_stock(
        db,
        product_id=product.id,
        title=product.title,
        before=before_qty,
        after=product.quantity,
    )
    if variant.quantity is not None:
        inventory_service.stage_sale(
            db,
            product_id=product.id,
            variant_id=variant.id,
            quantity=-quantity,
            unit_cost=variant_service.effective_unit_cost(product, variant),
        )
    price, sku, compare_at = row
    line = pricing_service.price_line(
        regular=pricing_service.regular_of(int(price), compare_at),
        price=int(price),
        stored_base=None,
        quantity=quantity,
        tiers=pricing_service.product_tiers(product, rules),
        rules=rules,
    )
    return line, product.title, product.slug, product.image_src, str(sku)


async def _number(db: AsyncSession) -> str:
    for _ in range(5):
        candidate = "IM-" + secrets.token_hex(4).upper()
        taken = await db.scalar(select(Order.id).where(Order.number == candidate))
        if taken is None:
            return candidate
    raise UnprocessableError("Could not allocate an order number")


async def _replay(db: AsyncSession, actor: str, key: str) -> Order | None:
    existing = (
        await db.execute(select(OrderIdempotency).where(OrderIdempotency.idempotency_key == key))
    ).scalar_one_or_none()
    if existing is None:
        return None
    if existing.actor != actor:
        raise ConflictError("This idempotency key was already used")
    return await _load(db, existing.order_id)


async def replayed(db: AsyncSession, shopper: Shopper, idempotency_key: str) -> OrderRead | None:
    """The order an earlier request with this key already placed, if any."""
    key = require_idempotency_key(idempotency_key)
    order = await _replay(db, shopper_actor(shopper), key)
    return _read(order) if order is not None else None


async def create_order(
    db: AsyncSession,
    shopper: Shopper,
    payload: OrderCreate,
    idempotency_key: str,
    background: BackgroundTasks | None = None,
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> OrderRead:
    key = require_idempotency_key(idempotency_key)
    actor = shopper_actor(shopper)
    replayed = await _replay(db, actor, key)
    if replayed is not None:
        return _read(replayed)
    telegram_notify.discard_low_stock(db)
    inventory_service.clear_pending_sales(db)

    requested = await _requested(db, shopper, payload)
    if not requested:
        raise UnprocessableError("Your cart is empty")

    rates = await delivery_service.fees(db)
    zone, fee, available = delivery_service.price_for(
        payload.district, payload.area, payload.delivery_zone, rates
    )
    if not available:
        raise UnprocessableError("Delivery is not available for this area")

    # Prices come only from the database rows and the pricing rules, never from the request.
    rules = await pricing_service.store_rules(db)
    priced: list[
        tuple[Requested, pricing_service.Line, str, str, str, str, Decimal | None, uuid.UUID | None]
    ] = []
    ordered = sorted(requested, key=lambda row: (row.product_id.hex, str(row.variant_id or "")))
    for row in ordered:
        product = await _product(db, row.product_id)
        variant = await variant_service.resolve_for_purchase(db, product, row.variant_id)
        line, title, slug, image_src, sku = await _claim(db, product, variant, row.quantity, rules)
        # Snapshot cost now (variant cost if set, else product cost); later buys never rewrite it.
        priced.append(
            (
                row,
                line,
                title,
                slug,
                image_src,
                sku,
                variant_service.effective_unit_cost(product, variant),
                product.category_id,
            )
        )

    subtotal = sum(line.line_total for _row, line, *_rest in priced)
    shipping = fee if priced else 0
    coupon_code: str | None = None
    coupon_discount: int | None = None
    priced_coupon: coupon_service.PricedCoupon | None = None
    if payload.coupon_code:
        money = [
            coupon_service.MoneyLine(row.product_id, category_id, line.line_total)
            for row, line, _title, _slug, _image, _sku, _cost, category_id in priced
        ]
        # Re-checked under a row lock. A code that failed since the quote rejects the order.
        priced_coupon = await coupon_service.lock_and_price(
            db, payload.coupon_code, money, payload.phone
        )
        coupon_code = priced_coupon.code
        coupon_discount = priced_coupon.discount
        if priced_coupon.free_delivery:
            shipping = 0
    taken = coupon_discount or 0
    total = max(subtotal - taken + shipping, 0)
    # The advance and the amount due are computed here from the server total, never taken
    # from the request. Bangla QR is refused while no QR image is set.
    advance_percent: int | None = None
    advance, due, reference = 0, total, ""
    if payload.payment_method == "bangla_qr":
        if await payment_service.bangla_qr_src(db) is None:
            raise UnprocessableError("Bangla QR পেমেন্ট এখন চালু নেই। ক্যাশ অন ডেলিভারি বেছে নিন।")
        advance_percent = payload.advance_percent
        advance, due = payment_service.advance_split(total, advance_percent or 0)
        reference = payload.payment_reference

    user_id = shopper.user.id if shopper.user is not None else None
    if user_id is None and payload.phone:
        from app.services.customer_auth_service import normalize_bd_phone

        norm_phone = normalize_bd_phone(payload.phone)
        if norm_phone:
            matched_user = await db.scalar(select(User).where(User.phone == norm_phone))
            if matched_user:
                user_id = matched_user.id

    order = Order(
        number=await _number(db),
        user_id=user_id,
        source=payload.source,
        channel=WEBSITE_CHANNEL,
        status=OrderStatus.NEW.value,
        payment_method=payload.payment_method,
        advance_percent=advance_percent,
        advance_amount=advance,
        due_amount=due,
        payment_reference=reference,
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
        total=total,
        coupon_code=coupon_code,
        coupon_discount=coupon_discount,
        inventory_held=True,
    )
    for row, line, title, slug, image_src, sku, unit_cost, _category_id in priced:
        order.items.append(
            OrderItem(
                product_id=row.product_id,
                variant_id=row.variant_id,
                sku=sku,
                title=title,
                slug=slug,
                image_src=image_src,
                unit_price=line.unit_price,
                quantity=row.quantity,
                line_total=line.line_total,
                selection=row.selection,
                regular_price=line.regular_price,
                base_discount=pricing_service.to_hundredths(line.base_percent),
                quantity_discount=pricing_service.to_hundredths(line.quantity_percent),
                total_discount=pricing_service.to_hundredths(line.total_percent),
                unit_cost=unit_cost,
            )
        )
    db.add(order)
    await db.flush()
    log_activity(
        db,
        order.id,
        None,
        ActivityAction.CREATED,
        "Order placed online",
        {"origin": OrderOrigin.ONLINE.value},
    )
    if priced_coupon is not None:
        coupon_service.stage_redemption(db, priced_coupon, order.id, payload.phone)
    inventory_service.attach_pending_sales(db, order.id)
    db.add(OrderIdempotency(actor=actor, idempotency_key=key, order_id=order.id))

    if payload.source == "cart":
        cart = await open_cart(db, shopper)
        if cart is not None:
            cart.items.clear()

    order_id = order.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        telegram_notify.discard_low_stock(db)
        replayed = await _replay(db, actor, key)
        if replayed is not None:
            return _read(replayed)
        raise ConflictError("Could not place the order. Try again.") from None
    db.expire_all()
    loaded = await _load(db, order_id)
    read = _read(loaded)
    # Only a newly committed order. Replays and status updates do not reach here.
    if background is not None:
        meta_capi.schedule_purchase(
            background,
            loaded,
            payload.tracking,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        await telegram_notify.notify_new_order(db, background, loaded)
        from app.services import push_service

        if push_service.is_configured():
            staff_ids = await push_service.staff_ids_with_module_read(db, "orders")
            if staff_ids:
                push_service.schedule_push_to_users(
                    background,
                    staff_ids,
                    "admin",
                    push_service.build_push_payload(
                        title=f"New Order #{loaded.number}",
                        body=f"{loaded.customer_name} · ৳{int(loaded.total)}",
                        url=f"/admin/orders/{loaded.id}",
                        tag=f"implesia-order-{loaded.id}",
                        scope="admin",
                        can_quick_reply=False,
                    ),
                )
    telegram_notify.flush_low_stock(db, background)
    await notification_service.create_order_status_notification(db, loaded, OrderStatus.NEW.value)
    await realtime_hub.publish(
        STAFF_ORDERS_CHANNEL,
        "order.new",
        {
            "id": str(loaded.id),
            "number": loaded.number,
            "status": loaded.status,
            "origin": loaded.origin,
            "customer_name": loaded.customer_name,
            "total": loaded.total,
            "payment_method": loaded.payment_method,
            "created_at": loaded.created_at.isoformat(),
        },
    )
    return read


def _like(term: str) -> str:
    escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _metrics(db: AsyncSession) -> AdminOrderMetrics:
    rows = (
        await db.execute(
            select(Order.status, func.count(), func.coalesce(func.sum(Order.total), 0)).group_by(
                Order.status
            )
        )
    ).all()
    counts = {status.value: 0 for status in OrderStatus}
    revenue = 0
    total = 0
    for status, count, money in rows:
        counts[str(status)] = int(count)
        total += int(count)
        if status not in _RESTOCK:
            revenue += int(money)
    return AdminOrderMetrics(
        orders=total,
        new=counts["new"],
        confirmed=counts["confirmed"],
        packed=counts["packed"],
        shipped=counts["shipped"],
        delivered=counts["delivered"],
        cancelled=counts["cancelled"],
        returned=counts["returned"],
        in_transit=counts["confirmed"] + counts["packed"] + counts["shipped"],
        revenue=revenue,
    )


def _status_clause(query: AdminOrderQuery) -> Any | None:
    if query.status is not None:
        return Order.status == query.status.value
    if query.scope == "transit":
        return Order.status.in_(
            [
                OrderStatus.CONFIRMED.value,
                OrderStatus.PACKED.value,
                OrderStatus.SHIPPED.value,
            ]
        )
    return None


async def list_orders(db: AsyncSession, query: AdminOrderQuery) -> AdminOrderList:
    conditions: list[Any] = []
    status_clause = _status_clause(query)
    if status_clause is not None:
        conditions.append(status_clause)
    if query.origin is not None:
        conditions.append(Order.origin == query.origin)
    if query.payment_method is not None:
        conditions.append(Order.payment_method == query.payment_method)
    if query.call_status is not None:
        conditions.append(Order.call_status == query.call_status.value)
    if query.courier:
        conditions.append(func.lower(Order.courier_name).like(_like(query.courier), escape="\\"))
    if query.payment_status is not None:
        paid = case(
            (
                and_(
                    Order.paid_amount == 0,
                    Order.payment_method == "bangla_qr",
                    Order.advance_amount > 0,
                ),
                Order.advance_amount,
            ),
            else_=Order.paid_amount,
        )
        if query.payment_status == "unpaid":
            conditions.append(paid <= 0)
        elif query.payment_status == "paid":
            conditions.append(paid >= Order.total)
        else:
            conditions.append(and_(paid > 0, paid < Order.total))
    if query.date_from is not None or query.date_to is not None:
        placed = func.coalesce(Order.ordered_at, Order.created_at)
        dialect = dialect_name(db)
        if query.date_from is not None:
            start = datetime.combine(query.date_from, time.min, tzinfo=SHOP)
            conditions.append(at_or_after(placed, start, dialect))
        if query.date_to is not None:
            end = datetime.combine(query.date_to + timedelta(days=1), time.min, tzinfo=SHOP)
            conditions.append(before(placed, end, dialect))
    if query.q:
        pattern = _like(query.q)
        title_match = (
            select(OrderItem.id)
            .where(OrderItem.order_id == Order.id)
            .where(func.lower(OrderItem.title).like(pattern, escape="\\"))
            .exists()
        )
        conditions.append(
            or_(
                func.lower(Order.number).like(pattern, escape="\\"),
                func.lower(Order.customer_name).like(pattern, escape="\\"),
                func.lower(Order.phone).like(pattern, escape="\\"),
                func.lower(Order.address).like(pattern, escape="\\"),
                title_match,
            )
        )

    def _apply(stmt: Select[Any]) -> Select[Any]:
        for condition in conditions:
            stmt = stmt.where(condition)
        return stmt

    total = int((await db.execute(_apply(select(func.count()).select_from(Order)))).scalar_one())
    ordering: tuple[Any, Any] = {
        "oldest": (Order.created_at.asc(), Order.id.asc()),
        "high": (Order.total.desc(), Order.id.desc()),
        "low": (Order.total.asc(), Order.id.asc()),
        "newest": (Order.created_at.desc(), Order.id.desc()),
    }[query.sort]
    rows: list[Order] = list(
        (
            await db.execute(
                _apply(select(Order).options(_ORDER_LOAD))
                .order_by(*ordering)
                .offset(query.offset)
                .limit(query.page_size)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    histories, duplicates = await _histories(db, rows)
    count_filters = [item for item in conditions if item is not status_clause]
    counted = await db.execute(
        select(Order.status, func.count()).where(*count_filters).group_by(Order.status)
    )
    status_counts = {status.value: 0 for status in OrderStatus}
    for status, count in counted.all():
        status_counts[str(status)] = int(count)
    return AdminOrderList(
        items=[
            _read(
                order,
                history=histories[order.id],
                duplicate=order.id in duplicates,
            )
            for order in rows
        ],
        total=total,
        page=query.page,
        page_size=query.page_size,
        pages=order_page_count(total, query.page_size),
        metrics=await _metrics(db),
        status_counts=StatusCounts(**status_counts),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def list_new_orders(db: AsyncSession, query: NewOrderQuery) -> NewOrderFeed:
    """Orders created after `since`, newest first. Only the columns the feed returns.

    `now` is captured before the query and is the next cursor. Rows created
    after that instant wait for the following poll, so a row is not returned
    twice when the client sends the previous `now` as `since`.
    """
    now = datetime.now(UTC)
    since = _as_utc(query.since) if query.since is not None else now - _NEW_ORDER_WINDOW
    rows = (
        await db.execute(
            select(
                Order.id,
                Order.number,
                Order.customer_name,
                Order.total,
                Order.payment_method,
                Order.created_at,
            )
            .where(Order.created_at > since, Order.created_at <= now)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(query.limit)
        )
    ).all()
    return NewOrderFeed(
        now=now,
        items=[
            NewOrderItem(
                id=row.id,
                number=str(row.number),
                customer_name=str(row.customer_name),
                total=int(row.total),
                payment_method=row.payment_method,
                created_at=_as_utc(row.created_at),
            )
            for row in rows
        ],
    )


def _mask_phone(phone: str) -> str:
    if len(phone) < 8:
        return phone
    return f"{phone[:3]}••••{phone[-3:]}"


def _public(order: Order, timeline: list[PublicTimelineEvent]) -> PublicOrderRead:
    return PublicOrderRead(
        number=order.number,
        status=order.status,
        customer_name=order.customer_name,
        phone=_mask_phone(order.phone),
        delivery_zone=order.delivery_zone,
        subtotal=order.subtotal,
        shipping=order.shipping,
        total=order.total,
        coupon_code=order.coupon_code,
        coupon_discount=order.coupon_discount,
        courier_name=order.courier_name,
        tracking_number=order.tracking_number,
        **_payment(order),
        items=[
            PublicOrderItemRead(
                title=item.title,
                slug=item.slug,
                product_id=item.product_id,
                image_src=item.image_src,
                unit_price=item.unit_price,
                quantity=item.quantity,
                line_total=item.line_total,
                variant_label=variant_label(item.selection),
                selection=selection_of(item.selection),
            )
            for item in order.items
        ],
        timeline=timeline,
        created_at=order.created_at,
    )


async def _timeline(db: AsyncSession, order: Order) -> list[PublicTimelineEvent]:
    """Status times the customer can see. No actor and no staff notes.

    Placed is ``created_at``. Later statuses come from ``status_changed``
    activity rows. ``delivered_at`` and ``returned_at`` fill a gap when that
    change was recorded on the order and not in the activity log.
    """
    rows = (
        (
            await db.execute(
                select(OrderActivity)
                .where(
                    OrderActivity.order_id == order.id,
                    OrderActivity.action == ActivityAction.STATUS_CHANGED.value,
                )
                .order_by(OrderActivity.created_at.asc(), OrderActivity.id.asc())
            )
        )
        .scalars()
        .all()
    )
    events = [PublicTimelineEvent(status=OrderStatus.NEW.value, at=_as_utc(order.created_at))]
    seen = {OrderStatus.NEW.value}
    for row in rows:
        detail = row.detail or {}
        target = detail.get("to")
        if not isinstance(target, str) or not target:
            continue
        events.append(PublicTimelineEvent(status=target, at=_as_utc(row.created_at)))
        seen.add(target)
    if order.delivered_at is not None and OrderStatus.DELIVERED.value not in seen:
        events.append(
            PublicTimelineEvent(status=OrderStatus.DELIVERED.value, at=_as_utc(order.delivered_at))
        )
    if order.returned_at is not None and OrderStatus.RETURNED.value not in seen:
        events.append(
            PublicTimelineEvent(status=OrderStatus.RETURNED.value, at=_as_utc(order.returned_at))
        )
    events.sort(key=lambda event: event.at)
    return events


async def _public_order(db: AsyncSession, order: Order) -> PublicOrderRead:
    return _public(order, await _timeline(db, order))


def _same_secret(stored: str, given: str) -> bool:
    if len(stored) != len(given):
        return False
    return hmac.compare_digest(stored, given)


async def lookup_order(db: AsyncSession, payload: OrderLookup) -> PublicOrderRead:
    if payload.number is not None:
        order = (
            await db.execute(
                select(Order).options(_ORDER_LOAD).where(Order.number == payload.number)
            )
        ).scalar_one_or_none()
        stored = order.phone if order is not None else "00000000000"
        if order is None or not _same_secret(stored, payload.phone):
            raise NotFoundError("Order not found")
        return await _public_order(db, order)
    needle = (payload.tracking_number or "").casefold()
    rows = list(
        (
            await db.execute(
                select(Order)
                .options(_ORDER_LOAD)
                .where(func.lower(Order.tracking_number) == needle)
                .order_by(Order.created_at.desc(), Order.id.desc())
                .limit(50)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    matched = [row for row in rows if _same_secret(row.phone, payload.phone)]
    if not matched:
        _same_secret("00000000000", payload.phone)
        raise NotFoundError("Order not found")
    return await _public_order(db, matched[0])


async def _histories(
    db: AsyncSession, orders: list[Order]
) -> tuple[dict[uuid.UUID, CustomerHistory], set[uuid.UUID]]:
    """Same-phone counts, and which of these orders have a sibling within 24 hours.

    Counts include the order itself. The window uses created_at, so an offline
    order dated in the past still warns about a checkout burst that happened now.
    """
    histories: dict[uuid.UUID, CustomerHistory] = {}
    duplicates: set[uuid.UUID] = set()
    if not orders:
        return histories, duplicates
    phones = list({order.phone for order in orders})
    grouped = (
        await db.execute(
            select(Order.phone, Order.status, func.count())
            .where(Order.phone.in_(phones))
            .group_by(Order.phone, Order.status)
        )
    ).all()
    by_phone: dict[str, dict[str, int]] = {}
    for phone, status, count in grouped:
        by_phone.setdefault(str(phone), {})[str(status)] = int(count)
    stamps = [_as_utc(order.created_at) for order in orders]
    low = min(stamps) - timedelta(hours=24)
    high = max(stamps) + timedelta(hours=24)
    nearby = (
        await db.execute(
            select(Order.id, Order.phone, Order.created_at).where(
                Order.phone.in_(phones),
                Order.created_at >= low,
                Order.created_at <= high,
            )
        )
    ).all()
    by_phone_times: dict[str, list[tuple[uuid.UUID, datetime]]] = {}
    for other_id, phone, created in nearby:
        by_phone_times.setdefault(str(phone), []).append((other_id, _as_utc(created)))
    for order in orders:
        counts = by_phone.get(order.phone, {})
        histories[order.id] = CustomerHistory(
            phone=order.phone,
            total_orders=sum(counts.values()),
            delivered=counts.get(OrderStatus.DELIVERED.value, 0),
            returned_cancelled=(
                counts.get(OrderStatus.RETURNED.value, 0)
                + counts.get(OrderStatus.CANCELLED.value, 0)
            ),
        )
        moment = _as_utc(order.created_at)
        for other_id, other_at in by_phone_times.get(order.phone, []):
            if other_id == order.id:
                continue
            if abs((moment - other_at).total_seconds()) <= 24 * 60 * 60:
                duplicates.add(order.id)
                break
    return histories, duplicates


async def _activities(db: AsyncSession, order_id: uuid.UUID) -> list[OrderActivityRead]:
    rows = (
        await db.execute(
            select(OrderActivity, User.full_name)
            .outerjoin(User, User.id == OrderActivity.actor_user_id)
            .where(OrderActivity.order_id == order_id)
            .order_by(OrderActivity.created_at.desc(), OrderActivity.id.desc())
            .limit(100)
        )
    ).all()
    return [
        OrderActivityRead(
            id=row.id,
            actor_user_id=row.actor_user_id,
            actor_name=name,
            action=row.action,
            summary=row.summary,
            detail=row.detail or {},
            created_at=_as_utc(row.created_at),
        )
        for row, name in rows
    ]


async def present(db: AsyncSession, order: Order, *, with_activity: bool = False) -> OrderRead:
    histories, duplicates = await _histories(db, [order])
    activity = await _activities(db, order.id) if with_activity else []
    return _read(
        order,
        history=histories[order.id],
        duplicate=order.id in duplicates,
        activity=activity,
    )


async def get_order(db: AsyncSession, order_id: uuid.UUID) -> OrderRead:
    return await present(db, await _load(db, order_id), with_activity=True)


async def _restore(
    db: AsyncSession,
    order: Order,
    *,
    stock_reason: str,
    actor_id: uuid.UUID | None,
) -> None:
    # Release the hold in one conditional update so two concurrent requests cannot both restock.
    released = (
        await db.execute(
            update(Order)
            .where(Order.id == order.id, Order.inventory_held.is_(True))
            .values(inventory_held=False)
            .returning(Order.id)
        )
    ).one_or_none()
    if released is None:
        return
    movement_type = (
        MovementType.RETURN.value
        if stock_reason == OrderStatus.RETURNED.value
        else MovementType.CANCEL.value
    )
    for item in order.items:
        if item.product_id is None:
            continue
        await release_units(
            db,
            product_id=item.product_id,
            variant_id=item.variant_id,
            quantity=item.quantity,
            order_id=order.id,
            actor_id=actor_id,
            movement_type=movement_type,
        )


async def release_units(
    db: AsyncSession,
    *,
    product_id: uuid.UUID,
    variant_id: uuid.UUID | None,
    quantity: int,
    order_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    movement_type: str,
    note: str = "",
) -> None:
    """Put `quantity` back onto a tracked bucket and write one movement.

    Unlimited stock (quantity NULL) changes nothing and writes nothing.
    A missing variant on a variant product has nothing to give back.
    """
    if quantity <= 0:
        return
    if variant_id is not None:
        await variant_service.lock_product(db, product_id)
        variant_row = await db.get(ProductVariant, variant_id, populate_existing=True)
        tracked = variant_row is not None and variant_row.quantity is not None
        await variant_service.release_stock(db, variant_id, quantity)
        await variant_service.rollup_by_id(db, product_id)
        if tracked:
            product = await db.get(Product, product_id)
            inventory_service.add_movement(
                db,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
                movement_type=movement_type,
                unit_cost=(
                    variant_service.effective_unit_cost(product, variant_row)
                    if product is not None
                    else (variant_row.cost_price if variant_row is not None else None)
                ),
                order_id=order_id,
                actor_id=actor_id,
                note=note,
            )
        return
    owner = await db.get(Product, product_id, populate_existing=True)
    if owner is not None and owner.has_variants:
        return
    tracked = owner is not None and owner.quantity is not None
    await db.execute(
        update(Product)
        .where(Product.id == product_id, Product.quantity.is_not(None))
        .values(quantity=Product.quantity + quantity)
    )
    await db.execute(
        update(Product)
        .where(Product.id == product_id)
        .where(Product.status == StockStatus.SOLD_OUT.value)
        .where(Product.quantity > 0)
        .values(status=StockStatus.AVAILABLE.value)
    )
    if tracked and owner is not None:
        inventory_service.add_movement(
            db,
            product_id=product_id,
            variant_id=None,
            quantity=quantity,
            movement_type=movement_type,
            unit_cost=owner.cost_price,
            order_id=order_id,
            actor_id=actor_id,
            note=note,
        )


def _status_assignments(target: str, order: Order | None = None) -> dict[str, Any]:
    """New status, plus the first delivery or return time.

    `coalesce` keeps a time that is already stored. A later transition into the same
    status does not replace it. For offline orders with a business date (`ordered_at`),
    delivering preserves `ordered_at` so backdated counter sales stay aligned in reports.
    """
    values: dict[str, Any] = {"status": target}
    now = datetime.now(UTC)
    if target == OrderStatus.DELIVERED.value:
        default_delivered_at = (
            order.ordered_at
            if order is not None
            and order.origin == OrderOrigin.OFFLINE.value
            and order.ordered_at is not None
            else now
        )
        values["delivered_at"] = func.coalesce(Order.delivered_at, default_delivered_at)
    elif target == OrderStatus.RETURNED.value:
        values["returned_at"] = func.coalesce(Order.returned_at, now)
    return values


async def change_status(
    db: AsyncSession,
    order: Order,
    target: str,
    *,
    actor_id: uuid.UUID | None,
) -> bool:
    """Move one order. Returns whether it became cancelled.

    Does not commit. A compare-and-set miss raises ConflictError without rolling
    the session back, so a caller that uses a savepoint can keep the other rows.
    """
    current = order.status
    if target not in ORDER_TRANSITIONS.get(current, frozenset()):
        allowed = ", ".join(next_statuses(current)) or "none (final status)"
        raise ConflictError(
            f"Cannot change an order from {current} to {target}. Allowed: {allowed}"
        )
    # The delivery/return time is written in the same statement and only while still NULL,
    # so the first timestamp stays.
    moved = (
        await db.execute(
            update(Order)
            .where(Order.id == order.id, Order.status == current)
            .values(**_status_assignments(target, order))
            .returning(Order.id)
        )
    ).one_or_none()
    db.expire(order, ["status", "delivered_at", "returned_at"])
    if moved is None:
        raise ConflictError("This order was changed by someone else. Reload and try again.")
    if target in _RESTOCK:
        await _restore(db, order, stock_reason=target, actor_id=actor_id)
    if target == OrderStatus.CANCELLED.value:
        # The use comes back. A return leaves the redemption counted.
        await coupon_service.cancel_for_order(db, order.id)
    await audit_service.record(
        db,
        actor_id=actor_id,
        action=AuditAction.ORDER_STATUS_CHANGED,
        target_type="order",
        target_id=order.id,
        metadata={"number": order.number, "from": current, "to": target},
    )
    log_activity(
        db,
        order.id,
        actor_id,
        ActivityAction.STATUS_CHANGED,
        f"Status {current} to {target}",
        {"from": current, "to": target},
    )
    return target == OrderStatus.CANCELLED.value


async def update_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    payload: OrderUpdate,
    *,
    actor: User | None = None,
    background: BackgroundTasks | None = None,
) -> OrderRead:
    telegram_notify.discard_low_stock(db)
    actor_id = actor.id if actor is not None else None
    order = await _load(db, order_id)
    became_cancelled = False
    sms_status: str | None = None
    status_changed_to: str | None = None
    if payload.status is not None and payload.status.value != order.status:
        target = payload.status.value
        try:
            became_cancelled = await change_status(db, order, target, actor_id=actor_id)
        except ConflictError:
            await db.rollback()
            raise
        status_changed_to = target
        if target in customer_notify.SEND_ON:
            sms_status = target
    before_courier = (order.courier_name, order.tracking_number)
    if payload.courier_name is not None:
        order.courier_name = payload.courier_name
    if payload.tracking_number is not None:
        order.tracking_number = payload.tracking_number
    if (order.courier_name, order.tracking_number) != before_courier:
        log_activity(
            db,
            order.id,
            actor_id,
            ActivityAction.COURIER_EDITED,
            "Courier updated",
            {
                "courier_name": order.courier_name,
                "tracking_number": order.tracking_number,
                "previous_courier_name": before_courier[0],
                "previous_tracking_number": before_courier[1],
            },
        )
    if payload.call_status is not None and payload.call_status.value != order.call_status:
        previous = order.call_status
        order.call_status = payload.call_status.value
        log_activity(
            db,
            order.id,
            actor_id,
            ActivityAction.CALL_STATUS_CHANGED,
            "Call status updated",
            {"from": previous, "to": order.call_status},
        )
    if payload.notes is not None and payload.notes != order.notes:
        order.notes = payload.notes
        log_activity(
            db,
            order.id,
            actor_id,
            ActivityAction.NOTE_CHANGED,
            "Note updated",
            {},
        )
    before_paid = effective_paid(order)
    before_ref = order.payment_reference or ""
    payment_changed = False
    if payload.paid_amount is not None:
        if payload.paid_amount > order.total:
            await db.rollback()
            raise UnprocessableError("Paid amount cannot be larger than the order total")
        expected_due = order.total - payload.paid_amount
        if payload.paid_amount != before_paid or order.due_amount != expected_due:
            order.paid_amount = payload.paid_amount
            order.due_amount = expected_due
            if payload.paid_amount == 0 and order.payment_method == "bangla_qr":
                order.advance_amount = 0
            payment_changed = True
    if payload.payment_reference is not None and payload.payment_reference != before_ref:
        order.payment_reference = payload.payment_reference
        payment_changed = True
    if payment_changed:
        new_paid = effective_paid(order)
        due_now = (
            order.due_amount if order.due_amount is not None else max(order.total - new_paid, 0)
        )
        log_activity(
            db,
            order.id,
            actor_id,
            ActivityAction.PAYMENT_UPDATED,
            f"Payment updated ({new_paid}/{order.total} BDT)",
            {
                "from_paid": before_paid,
                "to_paid": new_paid,
                "due_amount": due_now,
                "payment_method": order.payment_method,
                "payment_reference": order.payment_reference or "",
            },
        )
    order_id = order.id
    await db.commit()
    db.expire_all()
    loaded = await _load(db, order_id)
    # Offline orders do not send the staff cancel alert. Online cancel still does.
    if became_cancelled and loaded.origin != OrderOrigin.OFFLINE.value:
        telegram_notify.schedule_cancelled(background, loaded)
    if sms_status is not None:
        await customer_notify.schedule(db, background, loaded, sms_status)
    telegram_notify.flush_low_stock(db, background)
    if status_changed_to is not None and payload.notify_customer:
        await notification_service.create_order_status_notification(
            db, loaded, status_changed_to, language=payload.notification_language
        )
    return await present(db, loaded, with_activity=True)
