import hmac
import re
import secrets
import uuid
from typing import Any, NamedTuple

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.audit_event import AuditAction
from app.models.order import (
    ORDER_TRANSITIONS,
    Order,
    OrderIdempotency,
    OrderItem,
    OrderStatus,
    next_statuses,
)
from app.models.product import Product, ProductVariant, StockStatus
from app.models.user import User
from app.schemas.order import (
    AdminOrderList,
    AdminOrderMetrics,
    AdminOrderQuery,
    OrderCreate,
    OrderItemRead,
    OrderLookup,
    OrderQuoteRequest,
    OrderRead,
    OrderUpdate,
    PublicOrderItemRead,
    PublicOrderRead,
    QuoteLineRead,
    QuoteRead,
    order_page_count,
)
from app.services import audit_service, delivery_service, variant_service
from app.services.cart_service import MAX_QTY, Shopper, _cap, _purchasable, open_cart, shopper_actor
from app.services.product_options import resolve_selection, selection_of
from app.services.product_service import content_of

_KEY = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_ORDER_LOAD = selectinload(Order.items)
_RESTOCK = {OrderStatus.CANCELLED.value, OrderStatus.RETURNED.value}


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
        if item.quantity > MAX_QTY:
            raise UnprocessableError("A product can have at most 5 in an order")
    return list(merged.values())


def _read(order: Order) -> OrderRead:
    return OrderRead(
        id=order.id,
        number=order.number,
        source=order.source,
        status=order.status,
        payment_method="cod",
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
        courier_name=order.courier_name,
        tracking_number=order.tracking_number,
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
            )
            for item in order.items
        ],
        created_at=order.created_at,
        next_statuses=next_statuses(order.status),
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
) -> QuoteLineRead:
    available = _purchasable(product, variant)
    cap = _cap(product, variant) if available else 0
    minimum = variant_service.order_limits(product)[0]
    unit_price = variant.price if variant is not None else product.price
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
        line_total=unit_price * quantity if counted else 0,
        available=counted,
        max_quantity=cap,
        selection=selection_of(selection),
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
    lines = [
        _line(
            await _product(db, row.product_id),
            await _variant_row(db, row.variant_id),
            row.quantity,
            row.cart_item_id,
            row.selection,
        )
        for row in requested
    ]
    rates = await delivery_service.fees(db)
    return _totals(lines, payload.district, payload.area, payload.delivery_zone, rates)


async def _claim(
    db: AsyncSession, product: Product, variant: ProductVariant | None, quantity: int
) -> tuple[int, str, str, str, str]:
    """Take stock in one conditional update. The returned price is the locked row."""
    minimum, maximum = variant_service.order_limits(product)
    if quantity > maximum:
        raise UnprocessableError(f"A product can have at most {maximum} in an order")
    if quantity < minimum:
        raise UnprocessableError(f"The minimum order for this product is {minimum}")
    if variant is not None:
        return await _claim_variant(db, product, variant, quantity)
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
                Product.price, Product.title, Product.slug, Product.image_src, Product.quantity
            )
        )
    ).one_or_none()
    if row is None:
        if product.quantity is not None and 0 < product.quantity < quantity:
            raise UnprocessableError(
                "There is not enough stock for that quantity. Please choose fewer."
            )
        raise UnprocessableError("This product cannot be ordered")
    price, title, slug, image_src, left = row
    if left == 0:
        await db.execute(
            update(Product)
            .where(Product.id == product.id, Product.quantity == 0)
            .values(status=StockStatus.SOLD_OUT.value)
        )
    return int(price), str(title), str(slug), str(image_src), ""


async def _claim_variant(
    db: AsyncSession, product: Product, variant: ProductVariant, quantity: int
) -> tuple[int, str, str, str, str]:
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
    row = (await db.execute(stmt.returning(ProductVariant.price, ProductVariant.sku))).one_or_none()
    if row is None:
        if variant.quantity is not None and 0 < variant.quantity < quantity:
            raise UnprocessableError(
                "There is not enough stock for that quantity. Please choose fewer."
            )
        raise UnprocessableError("This product cannot be ordered")
    await variant_service.rollup_by_id(db, product.id)
    price, sku = row
    return int(price), product.title, product.slug, product.image_src, str(sku)


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
    db: AsyncSession, shopper: Shopper, payload: OrderCreate, idempotency_key: str
) -> OrderRead:
    key = require_idempotency_key(idempotency_key)
    actor = shopper_actor(shopper)
    replayed = await _replay(db, actor, key)
    if replayed is not None:
        return _read(replayed)

    requested = await _requested(db, shopper, payload)
    if not requested:
        raise UnprocessableError("Your cart is empty")

    rates = await delivery_service.fees(db)
    zone, fee, available = delivery_service.price_for(
        payload.district, payload.area, payload.delivery_zone, rates
    )
    if not available:
        raise UnprocessableError("Delivery is not available for this area")

    priced: list[tuple[Requested, int, str, str, str, str]] = []
    ordered = sorted(requested, key=lambda row: (row.product_id.hex, str(row.variant_id or "")))
    for row in ordered:
        product = await _product(db, row.product_id)
        variant = await variant_service.resolve_for_purchase(db, product, row.variant_id)
        price, title, slug, image_src, sku = await _claim(db, product, variant, row.quantity)
        priced.append((row, price, title, slug, image_src, sku))

    subtotal = sum(price * row.quantity for row, price, *_rest in priced)
    shipping = fee if priced else 0
    order = Order(
        number=await _number(db),
        user_id=shopper.user.id if shopper.user is not None else None,
        source=payload.source,
        status=OrderStatus.NEW.value,
        payment_method="cod",
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
        total=subtotal + shipping,
        inventory_held=True,
    )
    for row, price, title, slug, image_src, sku in priced:
        order.items.append(
            OrderItem(
                product_id=row.product_id,
                variant_id=row.variant_id,
                sku=sku,
                title=title,
                slug=slug,
                image_src=image_src,
                unit_price=price,
                quantity=row.quantity,
                line_total=price * row.quantity,
                selection=row.selection,
            )
        )
    db.add(order)
    await db.flush()
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
        replayed = await _replay(db, actor, key)
        if replayed is not None:
            return _read(replayed)
        raise ConflictError("Could not place the order. Try again.") from None
    db.expire_all()
    return _read(await _load(db, order_id))


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
        shipped=counts["shipped"],
        delivered=counts["delivered"],
        cancelled=counts["cancelled"],
        returned=counts["returned"],
        in_transit=counts["confirmed"] + counts["shipped"],
        revenue=revenue,
    )


async def list_orders(db: AsyncSession, query: AdminOrderQuery) -> AdminOrderList:
    conditions = []
    if query.status is not None:
        conditions.append(Order.status == query.status.value)
    elif query.scope == "transit":
        conditions.append(
            Order.status.in_([OrderStatus.CONFIRMED.value, OrderStatus.SHIPPED.value])
        )
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
    return AdminOrderList(
        items=[_read(order) for order in rows],
        total=total,
        page=query.page,
        page_size=query.page_size,
        pages=order_page_count(total, query.page_size),
        metrics=await _metrics(db),
    )


def _mask_phone(phone: str) -> str:
    if len(phone) < 8:
        return phone
    return f"{phone[:3]}••••{phone[-3:]}"


def _public(order: Order) -> PublicOrderRead:
    return PublicOrderRead(
        number=order.number,
        status=order.status,
        customer_name=order.customer_name,
        phone=_mask_phone(order.phone),
        delivery_zone=order.delivery_zone,
        subtotal=order.subtotal,
        shipping=order.shipping,
        total=order.total,
        courier_name=order.courier_name,
        tracking_number=order.tracking_number,
        payment_method="cod",
        items=[
            PublicOrderItemRead(
                title=item.title,
                slug=item.slug,
                image_src=item.image_src,
                unit_price=item.unit_price,
                quantity=item.quantity,
                line_total=item.line_total,
                selection=selection_of(item.selection),
            )
            for item in order.items
        ],
        created_at=order.created_at,
    )


def _same_secret(stored: str, given: str) -> bool:
    if len(stored) != len(given):
        return False
    return hmac.compare_digest(stored, given)


async def lookup_order(db: AsyncSession, payload: OrderLookup) -> PublicOrderRead:
    order = (
        await db.execute(select(Order).options(_ORDER_LOAD).where(Order.number == payload.number))
    ).scalar_one_or_none()
    stored = order.phone if order is not None else "00000000000"
    if order is None or not _same_secret(stored, payload.phone):
        raise NotFoundError("Order not found")
    return _public(order)


async def get_order(db: AsyncSession, order_id: uuid.UUID) -> OrderRead:
    return _read(await _load(db, order_id))


async def _restore(db: AsyncSession, order: Order) -> None:
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
    for item in order.items:
        if item.product_id is None:
            continue
        if item.variant_id is not None:
            await variant_service.lock_product(db, item.product_id)
            await variant_service.release_stock(db, item.variant_id, item.quantity)
            await variant_service.rollup_by_id(db, item.product_id)
            continue
        owner = await db.get(Product, item.product_id)
        if owner is not None and owner.has_variants:
            continue  # the variant was deleted; its stock row is gone, nothing to give back
        await db.execute(
            update(Product)
            .where(Product.id == item.product_id, Product.quantity.is_not(None))
            .values(quantity=Product.quantity + item.quantity)
        )
        await db.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .where(Product.status == StockStatus.SOLD_OUT.value)
            .where(Product.quantity > 0)
            .values(status=StockStatus.AVAILABLE.value)
        )


async def update_order(
    db: AsyncSession, order_id: uuid.UUID, payload: OrderUpdate, *, actor: User | None = None
) -> OrderRead:
    actor_id = actor.id if actor is not None else None
    order = await _load(db, order_id)
    if payload.status is not None and payload.status.value != order.status:
        current = order.status
        target = payload.status.value
        if target not in ORDER_TRANSITIONS.get(current, frozenset()):
            allowed = ", ".join(next_statuses(current)) or "none (final status)"
            raise ConflictError(
                f"Cannot change an order from {current} to {target}. Allowed: {allowed}"
            )
        # Compare-and-set on the status so a concurrent change is not silently overwritten.
        moved = (
            await db.execute(
                update(Order)
                .where(Order.id == order.id, Order.status == current)
                .values(status=target)
                .returning(Order.id)
            )
        ).one_or_none()
        if moved is None:
            await db.rollback()
            raise ConflictError("This order was changed by someone else. Reload and try again.")
        if target in _RESTOCK:
            await _restore(db, order)
        await audit_service.record(
            db,
            actor_id=actor_id,
            action=AuditAction.ORDER_STATUS_CHANGED,
            target_type="order",
            target_id=order.id,
            metadata={"number": order.number, "from": current, "to": target},
        )
    if payload.courier_name is not None:
        order.courier_name = payload.courier_name
    if payload.tracking_number is not None:
        order.tracking_number = payload.tracking_number
    order_id = order.id
    await db.commit()
    db.expire_all()
    return _read(await _load(db, order_id))
