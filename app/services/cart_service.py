import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError, UnprocessableError
from app.models.cart import Cart, CartItem
from app.models.product import Product, StockStatus
from app.models.user import User
from app.schemas.cart import (
    AdminCartItemRead,
    AdminCartList,
    AdminCartMetrics,
    AdminCartQuery,
    AdminCartRead,
    CartItemRead,
    CartOwnerRead,
    CartRead,
    cart_page_count,
)
from app.schemas.product import OptionChoice
from app.services import delivery_service
from app.services.product_options import resolve_selection, selection_of
from app.services.product_service import content_of

MAX_QTY = 5
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_CART_LOAD = (
    selectinload(Cart.items).selectinload(CartItem.product),
    selectinload(Cart.user),
)


@dataclass(frozen=True)
class Shopper:
    user: User | None = None
    guest_token: str | None = None


def _cap(product: Product) -> int:
    if product.quantity is None:
        return MAX_QTY
    return min(MAX_QTY, product.quantity)


def _purchasable(product: Product) -> bool:
    return bool(
        product.published and product.status == StockStatus.AVAILABLE and _cap(product) >= 1
    )


def _token(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not _TOKEN.fullmatch(text):
        return None
    return text


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def shopper_actor(shopper: Shopper) -> str:
    """Stable identity for an order idempotency key. Never the raw guest token."""
    if shopper.user is not None:
        return f"user:{shopper.user.id}"
    token = _token(shopper.guest_token)
    if token:
        return f"guest:{_hash(token)}"
    return "anonymous"


async def open_cart(db: AsyncSession, shopper: Shopper) -> Cart | None:
    cart, _token = await _open(db, shopper, create=False)
    return cart


def _empty(anonymous: bool, rates: delivery_service.StoreFees) -> CartRead:
    return CartRead(
        id=None,
        anonymous=anonymous,
        cart_token=None,
        items=[],
        item_count=0,
        subtotal=0,
        shipping=0,
        total=0,
        inside_dhaka=rates.inside,
        dhaka_suburban=rates.suburban,
        outside_dhaka=rates.outside,
        inside_enabled=rates.inside_on,
        suburban_enabled=rates.suburban_on,
        outside_enabled=rates.outside_on,
    )


def _lines(cart: Cart) -> tuple[list[CartItemRead], int, int]:
    items: list[CartItemRead] = []
    subtotal = 0
    count = 0
    for item in cart.items:
        product = item.product
        available = _purchasable(product)
        unit_price = product.price
        line_total = unit_price * item.quantity if available else 0
        if available:
            subtotal += line_total
            count += item.quantity
        items.append(
            CartItemRead(
                id=item.id,
                product_id=product.id,
                title=product.title,
                slug=product.slug,
                image_src=product.image_src,
                unit_price=unit_price,
                quantity=item.quantity,
                line_total=line_total,
                available=available,
                selection=selection_of(item.selection),
            )
        )
    return items, subtotal, count


def _read(cart: Cart, token: str | None, rates: delivery_service.StoreFees) -> CartRead:
    items, subtotal, count = _lines(cart)
    shipping = delivery_service.preview_shipping(count, rates)
    anonymous = cart.user_id is None
    return CartRead(
        id=cart.id,
        anonymous=anonymous,
        cart_token=token if anonymous else None,
        items=items,
        item_count=count,
        subtotal=subtotal,
        shipping=shipping,
        total=subtotal + shipping,
        inside_dhaka=rates.inside,
        dhaka_suburban=rates.suburban,
        outside_dhaka=rates.outside,
        inside_enabled=rates.inside_on,
        suburban_enabled=rates.suburban_on,
        outside_enabled=rates.outside_on,
    )


def _owner(cart: Cart) -> CartOwnerRead:
    if cart.user is None:
        return CartOwnerRead(kind="guest")
    return CartOwnerRead(
        kind="user",
        user_id=cart.user.id,
        email=cart.user.email,
        full_name=cart.user.full_name,
        role=cart.user.role.value,
    )


def _admin(cart: Cart, rates: delivery_service.StoreFees) -> AdminCartRead:
    items, subtotal, count = _lines(cart)
    shipping = delivery_service.preview_shipping(count, rates)
    detailed = [
        AdminCartItemRead(
            **item.model_dump(),
            added_at=next(row.created_at for row in cart.items if row.id == item.id),
        )
        for item in items
    ]
    return AdminCartRead(
        id=cart.id,
        owner=_owner(cart),
        items=detailed,
        item_count=count,
        subtotal=subtotal,
        shipping=shipping,
        total=subtotal + shipping,
        inside_dhaka=rates.inside,
        dhaka_suburban=rates.suburban,
        outside_dhaka=rates.outside,
        inside_enabled=rates.inside_on,
        suburban_enabled=rates.suburban_on,
        outside_enabled=rates.outside_on,
        created_at=cart.created_at,
        updated_at=cart.updated_at,
    )


def _stmt():
    return select(Cart).options(*_CART_LOAD)


async def _reload(db: AsyncSession, cart_id: uuid.UUID) -> Cart:
    db.expire_all()
    cart = (await db.execute(_stmt().where(Cart.id == cart_id))).scalar_one()
    return cart


async def _find_user(db: AsyncSession, user: User) -> Cart | None:
    return (await db.execute(_stmt().where(Cart.user_id == user.id))).scalar_one_or_none()


async def _find_guest(db: AsyncSession, token: str | None) -> Cart | None:
    if token is None:
        return None
    found = (
        await db.execute(_stmt().where(Cart.guest_token_hash == _hash(token)))
    ).scalar_one_or_none()
    return found


def _touch(cart: Cart) -> None:
    cart.updated_at = datetime.now(UTC)


async def _merge(db: AsyncSession, user_cart: Cart, guest: Cart) -> None:
    for item in list(guest.items):
        existing = next(
            (row for row in user_cart.items if row.product_id == item.product_id),
            None,
        )
        product = item.product
        room = _cap(product) if _purchasable(product) else item.quantity
        combined = item.quantity + (existing.quantity if existing else 0)
        quantity = min(room, combined)
        quantity = max(1, min(MAX_QTY, quantity))
        if existing is None:
            user_cart.items.append(CartItem(product_id=product.id, quantity=quantity))
        else:
            existing.quantity = quantity
    _touch(user_cart)
    await db.delete(guest)
    await db.commit()


async def _open(
    db: AsyncSession, shopper: Shopper, *, create: bool
) -> tuple[Cart | None, str | None]:
    token = _token(shopper.guest_token)
    if shopper.user is not None:
        cart = await _find_user(db, shopper.user)
        guest = await _find_guest(db, token)
        if guest is not None and (cart is None or guest.id != cart.id):
            if cart is None:
                guest.user_id = shopper.user.id
                guest.guest_token_hash = None
                _touch(guest)
                await db.commit()
                return await _reload(db, guest.id), None
            await _merge(db, cart, guest)
            return await _reload(db, cart.id), None
        if cart is None and create:
            cart = Cart(user_id=shopper.user.id)
            db.add(cart)
            await db.commit()
            await db.refresh(cart)
            return await _reload(db, cart.id), None
        return cart, None

    guest = await _find_guest(db, token)
    if guest is not None:
        return guest, token
    if not create:
        return None, None
    raw = secrets.token_urlsafe(32)
    cart = Cart(guest_token_hash=_hash(raw))
    db.add(cart)
    await db.commit()
    await db.refresh(cart)
    return await _reload(db, cart.id), raw


async def _rates(db: AsyncSession) -> delivery_service.StoreFees:
    return await delivery_service.fees(db)


async def get_cart(db: AsyncSession, shopper: Shopper) -> CartRead:
    rates = await _rates(db)
    cart, token = await _open(db, shopper, create=False)
    if cart is None:
        return _empty(shopper.user is None, rates)
    return _read(cart, token, rates)


async def _product(db: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await db.get(Product, product_id)
    if product is None or not product.published:
        raise NotFoundError("Product not found")
    return product


def _ensure_room(product: Product, next_quantity: int) -> None:
    if not _purchasable(product):
        raise UnprocessableError("This product cannot be added to the cart")
    cap = _cap(product)
    if next_quantity > cap:
        if product.quantity is not None and product.quantity < MAX_QTY:
            raise UnprocessableError(f"Only {cap} are available")
        raise UnprocessableError("A product can have at most 5 in the cart")


async def add_item(
    db: AsyncSession,
    shopper: Shopper,
    product_id: uuid.UUID,
    quantity: int,
    choices: list[OptionChoice],
) -> CartRead:
    cart, token = await _open(db, shopper, create=True)
    if cart is None:
        raise NotFoundError("Cart item not found")
    product = await _product(db, product_id)
    chosen = [item.model_dump() for item in resolve_selection(content_of(product), choices)]
    existing = next((item for item in cart.items if item.product_id == product.id), None)
    next_quantity = quantity + (existing.quantity if existing else 0)
    _ensure_room(product, next_quantity)
    if existing is None:
        cart.items.append(CartItem(product_id=product.id, quantity=next_quantity, selection=chosen))
    else:
        existing.quantity = next_quantity
        if chosen:
            existing.selection = chosen
    _touch(cart)
    await db.commit()
    rates = await _rates(db)
    return _read(await _reload(db, cart.id), token, rates)


async def _owned(db: AsyncSession, shopper: Shopper) -> tuple[Cart, str | None]:
    cart, token = await _open(db, shopper, create=False)
    if cart is None:
        raise NotFoundError("Cart item not found")
    return cart, token


async def set_quantity(
    db: AsyncSession, shopper: Shopper, item_id: uuid.UUID, quantity: int
) -> CartRead:
    cart, token = await _owned(db, shopper)
    item = next((row for row in cart.items if row.id == item_id), None)
    if item is None:
        raise NotFoundError("Cart item not found")
    _ensure_room(item.product, quantity)
    item.quantity = quantity
    _touch(cart)
    await db.commit()
    rates = await _rates(db)
    return _read(await _reload(db, cart.id), token, rates)


async def remove_item(db: AsyncSession, shopper: Shopper, item_id: uuid.UUID) -> CartRead:
    cart, token = await _owned(db, shopper)
    item = next((row for row in cart.items if row.id == item_id), None)
    if item is None:
        raise NotFoundError("Cart item not found")
    cart.items.remove(item)
    _touch(cart)
    await db.commit()
    rates = await _rates(db)
    return _read(await _reload(db, cart.id), token, rates)


async def clear_cart(db: AsyncSession, shopper: Shopper) -> CartRead:
    rates = await _rates(db)
    cart, token = await _open(db, shopper, create=False)
    if cart is None:
        return _empty(shopper.user is None, rates)
    cart.items.clear()
    _touch(cart)
    await db.commit()
    return _read(await _reload(db, cart.id), token, rates)


def _like(term: str) -> str:
    escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _has_items():
    return select(CartItem.id).where(CartItem.cart_id == Cart.id).exists()


async def list_carts(db: AsyncSession, query: AdminCartQuery) -> AdminCartList:
    conditions = [_has_items()]
    if query.owner == "user":
        conditions.append(Cart.user_id.is_not(None))
    elif query.owner == "guest":
        conditions.append(Cart.guest_token_hash.is_not(None))
    if query.q:
        pattern = _like(query.q)
        user_match = (
            select(User.id)
            .where(User.id == Cart.user_id)
            .where(
                or_(
                    func.lower(User.email).like(pattern, escape="\\"),
                    func.lower(User.full_name).like(pattern, escape="\\"),
                )
            )
            .exists()
        )
        product_match = (
            select(CartItem.id)
            .join(Product, Product.id == CartItem.product_id)
            .where(CartItem.cart_id == Cart.id)
            .where(func.lower(Product.title).like(pattern, escape="\\"))
            .exists()
        )
        conditions.append(or_(user_match, product_match))

    def _apply(stmt):
        for condition in conditions:
            stmt = stmt.where(condition)
        return stmt

    total = int((await db.execute(_apply(select(func.count()).select_from(Cart)))).scalar_one())
    rows = (
        (
            await db.execute(
                _apply(_stmt())
                .order_by(Cart.updated_at.desc(), Cart.id.desc())
                .offset(query.offset)
                .limit(query.page_size)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    metrics = await _metrics(db)
    rates = await _rates(db)
    return AdminCartList(
        items=[_admin(cart, rates) for cart in rows],
        total=total,
        page=query.page,
        page_size=query.page_size,
        pages=cart_page_count(total, query.page_size),
        metrics=metrics,
    )


async def _metrics(db: AsyncSession) -> AdminCartMetrics:
    populated = _has_items()
    carts, user_carts, guest_carts = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((Cart.user_id.is_not(None), 1), else_=0)), 0),
                func.coalesce(func.sum(case((Cart.guest_token_hash.is_not(None), 1), else_=0)), 0),
            )
            .select_from(Cart)
            .where(populated)
        )
    ).one()
    units = (await db.execute(select(func.coalesce(func.sum(CartItem.quantity), 0)))).scalar_one()
    return AdminCartMetrics(
        carts=int(carts or 0),
        user_carts=int(user_carts or 0),
        guest_carts=int(guest_carts or 0),
        units=int(units or 0),
    )


async def get_admin_cart(db: AsyncSession, cart_id: uuid.UUID) -> AdminCartRead:
    cart = (await db.execute(_stmt().where(Cart.id == cart_id))).scalar_one_or_none()
    if cart is None:
        raise NotFoundError("Cart not found")
    rates = await _rates(db)
    return _admin(cart, rates)
