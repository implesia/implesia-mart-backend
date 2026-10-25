"""Variant stock, uniqueness and cart indexes, on PostgreSQL."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import UnprocessableError
from app.models.cart import Cart, CartItem
from app.models.order import Order
from app.models.product import Product, ProductVariant, StockStatus
from app.schemas.order import OrderCreate, OrderLineInput
from app.services import order_service, variant_service
from app.services.cart_service import Shopper
from tests.integration.helpers import product

pytestmark = pytest.mark.postgres


def _variant(
    product_id: uuid.UUID, key: str, *, quantity: int | None = 1, sku: str = "", price: int = 500
) -> ProductVariant:
    return ProductVariant(
        product_id=product_id,
        options={"size": key},
        option_key=f"size={key}",
        sku=sku,
        price=price,
        quantity=quantity,
    )


async def _seed(
    pg: async_sessionmaker[AsyncSession], *quantities: int | None
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    async with pg() as db:
        parent = product()
        parent.has_variants = True
        db.add(parent)
        await db.flush()
        rows = [_variant(parent.id, f"v{i}", quantity=q) for i, q in enumerate(quantities)]
        db.add_all(rows)
        await db.flush()
        await variant_service.rollup(db, parent)
        await db.commit()
        return parent.id, [row.id for row in rows]


def _order(product_id: uuid.UUID, variant_id: uuid.UUID, quantity: int = 1) -> OrderCreate:
    return OrderCreate(
        source="direct",
        customer_name="Race Buyer",
        phone="01700000000",
        district="ঢাকা",
        area="গুলশান",
        address="House 12, Road 4, Gulshan",
        items=[OrderLineInput(product_id=product_id, variant_id=variant_id, quantity=quantity)],
    )


async def test_duplicate_combination_and_case_insensitive_sku_are_refused(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    product_id, _ids = await _seed(pg, 1)
    async with pg() as db:
        db.add(_variant(product_id, "v0"))
        with pytest.raises(IntegrityError):
            await db.commit()
    async with pg() as db:
        db.add(_variant(product_id, "a", sku="Abc-1"))
        await db.commit()
    async with pg() as db:
        db.add(_variant(product_id, "b", sku="aBC-1"))
        with pytest.raises(IntegrityError):
            await db.commit()
    async with pg() as db:  # empty SKUs never clash
        db.add_all([_variant(product_id, "c"), _variant(product_id, "d")])
        await db.commit()


async def test_variant_check_constraints(pg: async_sessionmaker[AsyncSession]) -> None:
    product_id, _ids = await _seed(pg, 1)
    for bad in (
        _variant(product_id, "n1", price=-1),
        _variant(product_id, "n2", quantity=-1),
    ):
        async with pg() as db:
            db.add(bad)
            with pytest.raises(IntegrityError):
                await db.commit()
    async with pg() as db:
        row = _variant(product_id, "n3", price=100)
        row.compare_at_price = 50
        db.add(row)
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_order_quantity_limits_are_checked_by_the_database(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    for minimum, maximum in ((0, None), (6, None), (3, 2), (1, 6)):
        async with pg() as db:
            row = product()
            row.min_order_quantity = minimum
            row.max_order_quantity = maximum
            db.add(row)
            with pytest.raises(IntegrityError):
                await db.commit()


async def test_cart_keeps_one_line_per_product_or_per_variant(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    product_id, ids = await _seed(pg, 5, 5)
    async with pg() as db:
        cart = Cart(guest_token_hash=uuid.uuid4().hex)
        db.add(cart)
        await db.flush()
        db.add_all(
            [
                CartItem(cart_id=cart.id, product_id=product_id, variant_id=ids[0], quantity=1),
                CartItem(cart_id=cart.id, product_id=product_id, variant_id=ids[1], quantity=1),
            ]
        )
        await db.commit()
        cart_id = cart.id
    async with pg() as db:
        db.add(CartItem(cart_id=cart_id, product_id=product_id, variant_id=ids[0], quantity=1))
        with pytest.raises(IntegrityError):
            await db.commit()
    async with pg() as db:  # a plain line is still unique per product
        other = product()
        db.add(other)
        await db.flush()
        db.add(CartItem(cart_id=cart_id, product_id=other.id, quantity=1))
        await db.commit()
        db.add(CartItem(cart_id=cart_id, product_id=other.id, quantity=1))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_last_variant_unit_is_sold_once_and_the_roll_up_is_consistent(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    product_id, ids = await _seed(pg, 1, 1)

    async def buy(token: str, variant_id: uuid.UUID) -> str:
        async with pg() as db:
            try:
                placed = await order_service.create_order(
                    db, Shopper(guest_token=token), _order(product_id, variant_id), uuid.uuid4().hex
                )
            except UnprocessableError as exc:
                await db.rollback()
                return exc.message
        return placed.number

    # two buyers for variant 0, one for variant 1, all at once
    results = await asyncio.wait_for(
        asyncio.gather(
            buy("guest-token-buyer-a-0001", ids[0]),
            buy("guest-token-buyer-b-0002", ids[0]),
            buy("guest-token-buyer-c-0003", ids[1]),
        ),
        timeout=20,
    )
    assert sum(item.startswith("IM-") for item in results) == 2
    async with pg() as db:
        stock = {
            row.id: row.quantity
            for row in (await db.execute(select(ProductVariant))).scalars().all()
        }
        assert stock == {ids[0]: 0, ids[1]: 0}
        parent = await db.get(Product, product_id)
        assert parent is not None
        assert parent.quantity == 0 and parent.status == StockStatus.SOLD_OUT.value
        assert await db.scalar(select(func.count()).select_from(Order)) == 2


async def test_concurrent_orders_on_different_variants_never_corrupt_the_roll_up(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    product_id, ids = await _seed(pg, 5, 5, 5)

    async def buy(index: int) -> None:
        async with pg() as db:
            await order_service.create_order(
                db,
                Shopper(guest_token=f"guest-token-buyer-{index}-00000001"),
                _order(product_id, ids[index], 2),
                uuid.uuid4().hex,
            )

    await asyncio.wait_for(asyncio.gather(*(buy(i) for i in range(3))), timeout=20)
    async with pg() as db:
        parent = await db.get(Product, product_id)
        assert parent is not None and parent.quantity == 9
        total = await db.scalar(select(func.sum(ProductVariant.quantity)))
        assert total == 9
