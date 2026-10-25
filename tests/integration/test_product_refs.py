"""Deleting a product keeps orders readable: the tracking link must not point at it (PG FK)."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.product import Product
from app.schemas.order import OrderCreate, OrderLineInput, OrderLookup
from app.services import order_service
from app.services.cart_service import Shopper
from tests.integration.helpers import product

pytestmark = pytest.mark.postgres


async def test_public_order_item_drops_product_id_after_the_product_is_deleted(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        parent = product(quantity=5)
        db.add(parent)
        await db.commit()
        product_id, slug = parent.id, parent.slug
        placed = await order_service.create_order(
            db,
            Shopper(guest_token="guest-token-url-ref-00001"),
            OrderCreate(
                source="direct",
                customer_name="Ref Buyer",
                phone="01700000000",
                district="ঢাকা",
                area="গুলশান",
                address="House 12, Road 4, Gulshan",
                items=[OrderLineInput(product_id=product_id, quantity=1)],
            ),
            uuid.uuid4().hex,
        )
        lookup = OrderLookup(number=placed.number, phone="01700000000")
        before = await order_service.lookup_order(db, lookup)
        assert before.items[0].product_id == product_id

    async with pg() as db:
        gone = await db.get(Product, product_id)
        assert gone is not None
        await db.delete(gone)
        await db.commit()

    async with pg() as db:
        after = await order_service.lookup_order(db, lookup)
        assert after.items[0].product_id is None
        assert after.items[0].slug == slug
