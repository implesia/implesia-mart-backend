"""Concurrent checkouts cannot redeem a coupon more times than its limit."""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import CouponError
from app.models.coupon import Coupon, CouponRedemption
from app.models.product import Product
from app.schemas.order import OrderCreate, OrderLineInput
from app.services import order_service
from app.services.cart_service import Shopper
from tests.integration.helpers import product

pytestmark = pytest.mark.postgres


async def test_parallel_orders_stop_at_the_usage_limit(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        row = product(price=1000, quantity=20)
        coupon = Coupon(
            code="RACE2",
            discount_type="fixed",
            value=Decimal("50"),
            usage_limit_total=2,
            is_active=True,
            free_delivery=False,
            first_order_only=False,
        )
        db.add(row)
        db.add(coupon)
        await db.commit()
        product_id = row.id

    async def place(index: int) -> str:
        payload = OrderCreate(
            source="direct",
            items=[OrderLineInput(product_id=product_id, quantity=1)],
            customer_name="Rina Akter",
            phone=f"0171000000{index}",
            email="",
            district="ঢাকা",
            area="গুলশান",
            address="House 12, Road 4",
            notes="",
            coupon_code="RACE2",
        )
        async with pg() as db:
            try:
                await order_service.create_order(
                    db, Shopper(), payload, uuid.uuid4().hex, None
                )
            except CouponError as exc:
                await db.rollback()
                return exc.code
            return "ok"

    results = await asyncio.gather(*(place(index) for index in range(1, 7)))
    assert results.count("ok") == 2
    assert results.count("coupon_usage_limit") == 4

    async with pg() as db:
        uses = await db.scalar(
            select(func.count())
            .select_from(CouponRedemption)
            .where(CouponRedemption.cancelled_at.is_(None))
        )
        left = await db.scalar(select(Product.quantity).where(Product.id == product_id))
    assert uses == 2
    assert left == 18
