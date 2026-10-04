"""Two buyers racing for the last unit, on PostgreSQL."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import UnprocessableError
from app.models.order import Order
from app.models.product import Product, StockStatus
from app.schemas.order import OrderCreate, OrderLineInput
from app.services import order_service
from app.services.cart_service import Shopper
from tests.integration.helpers import product

pytestmark = pytest.mark.postgres
_STOCK_REJECTION = "This product cannot be ordered"


def _order(product_id: uuid.UUID) -> OrderCreate:
    return OrderCreate(
        source="direct",
        customer_name="Race Buyer",
        phone="01700000000",
        district="ঢাকা",
        area="গুলশান",
        address="House 12, Road 4, Gulshan",
        items=[OrderLineInput(product_id=product_id, quantity=1)],
    )


async def test_one_unit_can_be_bought_only_once(
    pg: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with pg() as db:
        row = product()
        db.add(row)
        await db.commit()
        product_id = row.id

    started = asyncio.Barrier(2)
    real_claim = order_service._claim

    async def gated(db: AsyncSession, item: Product, quantity: int) -> tuple[int, str, str, str]:
        await started.wait()
        return await real_claim(db, item, quantity)

    monkeypatch.setattr(order_service, "_claim", gated)

    async def buy(token: str) -> str:
        async with pg() as db:
            try:
                placed = await order_service.create_order(
                    db,
                    Shopper(guest_token=token),
                    _order(product_id),
                    uuid.uuid4().hex,
                )
            except UnprocessableError as exc:
                await db.rollback()
                return exc.message
        return placed.number

    results = await asyncio.wait_for(
        asyncio.gather(
            buy("guest-token-buyer-a-0001"),
            buy("guest-token-buyer-b-0002"),
        ),
        timeout=15,
    )
    assert sum(item.startswith("IM-") for item in results) == 1
    assert results.count(_STOCK_REJECTION) == 1

    async with pg() as db:
        left = await db.get(Product, product_id)
        assert left is not None
        assert left.quantity == 0
        assert left.status == StockStatus.SOLD_OUT.value
        orders = await db.scalar(select(func.count()).select_from(Order))
        assert orders == 1
