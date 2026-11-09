"""On PostgreSQL the delivery stamp is timezone-aware UTC and is not replaced."""

from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.order import Order, OrderStatus
from app.schemas.order import OrderUpdate
from app.services import order_service
from tests.integration.helpers import order

pytestmark = pytest.mark.postgres


async def test_delivery_stamp_is_utc_and_a_second_transition_keeps_it(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        row = order()
        row.status = OrderStatus.SHIPPED.value
        db.add(row)
        await db.commit()
        order_id = row.id

        delivered = await order_service.update_order(
            db, order_id, OrderUpdate(status=OrderStatus.DELIVERED)
        )
        assert delivered.delivered_at is not None
        assert delivered.returned_at is None
        assert delivered.delivered_at.tzinfo is not None
        assert delivered.delivered_at.utcoffset() == timedelta(0)
        first = delivered.delivered_at

        await db.execute(update(Order).where(Order.id == order_id).values(status="shipped"))
        await db.commit()
        again = await order_service.update_order(
            db, order_id, OrderUpdate(status=OrderStatus.DELIVERED)
        )
        assert again.delivered_at == first

        returned = await order_service.update_order(
            db, order_id, OrderUpdate(status=OrderStatus.RETURNED)
        )
        assert returned.delivered_at == first
        assert returned.returned_at is not None
        assert returned.returned_at.tzinfo is not None
        assert returned.returned_at.utcoffset() == timedelta(0)
