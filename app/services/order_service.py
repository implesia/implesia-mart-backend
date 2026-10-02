import re
import secrets
import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.models.order import Order, OrderIdempotency, OrderItem, OrderStatus
from app.models.product import Product, StockStatus
from app.schemas.order import (
    AdminOrderList,
    AdminOrderMetrics,
    AdminOrderQuery,
    OrderCreate,
    OrderItemRead,
    OrderQuoteRequest,
    OrderRead,
    OrderUpdate,
    QuoteLineRead,
    QuoteRead,
    order_page_count,
)
from app.services import delivery_service
from app.services.cart_service import MAX_QTY, Shopper, _cap, _purchasable, open_cart, shopper_actor

_KEY = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_ORDER_LOAD = selectinload(Order.items)
_RESTOCK = {OrderStatus.CANCELLED.value, OrderStatus.RETURNED.value}


def require_idempotency_key(value: str) -> str:
    key = value.strip()
    if not _KEY.fullmatch(key):
        raise UnprocessableError("Idempotency-Key must be 8 to 80 letters, numbers, _ or -")
    return key


def _merge(items: list[tuple[uuid.UUID, int]]) -> list[tuple[uuid.UUID, int]]:
    merged: dict[uuid.UUID, int] = {}
    for product_id, quantity in items:
        merged[product_id] = merged.get(product_id, 0) + quantity
    for quantity in merged.values():
        if quantity > MAX_QTY:
            raise UnprocessableError("A product can have at most 5 in an order")
    return list(merged.items())


def _read(order: Order) -> OrderRead:
    return OrderRead(
        id=order.id,
        number=order.number,
        source=order.source,  # type: ignore[arg-type]
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
        delivery_zone=order.delivery_zone,  # type: ignore[arg-type]
        subtotal=order.subtotal,
        shipping=order.shipping,
        total=order.total,
        courier_name=order.courier_name,
        tracking_number=order.tracking_number,
        items=[
            OrderItemRead(
                id=item.id,
                product_id=item.product_id,
                title=item.title,
                slug=item.slug,
                image_src=item.image_src,
                unit_price=item.unit_price,
                quantity=item.quantity,
                line_total=item.line_total,
            )
            for item in order.items
        ],
        created_at=order.created_at,
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
) -> list[tuple[uuid.UUID, int, uuid.UUID | None]]:
    if payload.source == "direct":
        merged = _merge([(item.product_id, item.quantity) for item in payload.items])
        return [(product_id, quantity, None) for product_id, quantity in merged]

    cart = await open_cart(db, shopper)
    if cart is None or not cart.items:
        return []
    return [(item.product_id, item.quantity, item.id) for item in cart.items]


async def _product(db: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await db.get(Product, product_id)
    if product is None or not product.published:
        raise NotFoundError("Product not found")
    return product


def _line(product: Product, quantity: int, cart_item_id: uuid.UUID | None) -> QuoteLineRead:
    available = _purchasable(product)
    cap = _cap(product) if available else 0
    unit_price = product.price
    counted = available and 1 <= quantity <= max(cap, 0)
    return QuoteLineRead(
        product_id=product.id,
        cart_item_id=cart_item_id,
        title=product.title,
        slug=product.slug,
        image_src=product.image_src,
        unit_price=unit_price,
        quantity=quantity,
        line_total=unit_price * quantity if counted else 0,
        available=counted,
        max_quantity=cap,
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
    zone, fee = delivery_service.price_for(district, area, declared, rates)
    shipping = fee if count else 0
    return QuoteRead(
        items=lines,
        item_count=count,
        subtotal=subtotal,
        shipping=shipping,
        total=subtotal + shipping,
        delivery_zone=zone,  # type: ignore[arg-type]
    )


async def quote(db: AsyncSession, shopper: Shopper, payload: OrderQuoteRequest) -> QuoteRead:
    requested = await _requested(db, shopper, payload)
    lines = [
        _line(await _product(db, product_id), quantity, cart_item_id)
        for product_id, quantity, cart_item_id in requested
    ]
    rates = await delivery_service.fees(db)
    return _totals(lines, payload.district, payload.area, payload.delivery_zone, rates)


async def _claim(db: AsyncSession, product: Product, quantity: int) -> tuple[int, str, str, str]:
    """Take stock in one conditional update. The returned price is the locked row."""
    if quantity > MAX_QTY:
        raise UnprocessableError("A product can have at most 5 in an order")
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
        cap = _cap(product)
        if product.quantity is not None and 0 < product.quantity < quantity:
            raise UnprocessableError(f"Only {cap} are available")
        raise UnprocessableError("This product cannot be ordered")
    price, title, slug, image_src, left = row
    if left == 0:
        await db.execute(
            update(Product)
            .where(Product.id == product.id, Product.quantity == 0)
            .values(status=StockStatus.SOLD_OUT.value)
        )
    return int(price), str(title), str(slug), str(image_src)


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

    priced: list[tuple[uuid.UUID, int, int, str, str, str]] = []
    for product_id, quantity, _cart_item_id in sorted(requested, key=lambda row: row[0].hex):
        product = await _product(db, product_id)
        price, title, slug, image_src = await _claim(db, product, quantity)
        priced.append((product_id, quantity, price, title, slug, image_src))

    subtotal = sum(price * quantity for _id, quantity, price, *_rest in priced)
    rates = await delivery_service.fees(db)
    zone, fee = delivery_service.price_for(
        payload.district, payload.area, payload.delivery_zone, rates
    )
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
    for product_id, quantity, price, title, slug, image_src in priced:
        order.items.append(
            OrderItem(
                product_id=product_id,
                title=title,
                slug=slug,
                image_src=image_src,
                unit_price=price,
                quantity=quantity,
                line_total=price * quantity,
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

    def _apply(stmt):
        for condition in conditions:
            stmt = stmt.where(condition)
        return stmt

    total = int((await db.execute(_apply(select(func.count()).select_from(Order)))).scalar_one())
    ordering = {
        "oldest": (Order.created_at.asc(), Order.id.asc()),
        "high": (Order.total.desc(), Order.id.desc()),
        "low": (Order.total.asc(), Order.id.asc()),
        "newest": (Order.created_at.desc(), Order.id.desc()),
    }[query.sort]
    rows = (
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


async def get_order(db: AsyncSession, order_id: uuid.UUID) -> OrderRead:
    return _read(await _load(db, order_id))


async def _restore(db: AsyncSession, order: Order) -> None:
    if not order.inventory_held:
        return
    for item in order.items:
        if item.product_id is None:
            continue
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
    order.inventory_held = False


async def update_order(db: AsyncSession, order_id: uuid.UUID, payload: OrderUpdate) -> OrderRead:
    order = await _load(db, order_id)
    if payload.status is not None and payload.status.value != order.status:
        if payload.status.value in _RESTOCK:
            await _restore(db, order)
        order.status = payload.status.value
    if payload.courier_name is not None:
        order.courier_name = payload.courier_name
    if payload.tracking_number is not None:
        order.tracking_number = payload.tracking_number
    order_id = order.id
    await db.commit()
    db.expire_all()
    return _read(await _load(db, order_id))
