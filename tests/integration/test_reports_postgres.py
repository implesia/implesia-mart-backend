"""The report SQL on PostgreSQL, including the Asia/Dhaka midnight boundary."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.order import OrderItem
from app.services.report_service import ReportRequest, sales_summary, trend_report
from tests.integration.helpers import order, product

pytestmark = pytest.mark.postgres


async def test_postgres_splits_sales_at_dhaka_midnight(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        lamp = product(price=500, quantity=5)
        lamp.cost_price = Decimal("10.00")
        db.add(lamp)
        await db.flush()

        early = order()
        early.channel = "website"
        early.status = "delivered"
        early.delivered_at = datetime(2026, 11, 9, 17, 59, tzinfo=UTC)
        early.subtotal = 500
        early.shipping = 70
        early.total = 570

        late = order()
        late.channel = None
        late.status = "delivered"
        late.delivered_at = datetime(2026, 11, 9, 18, 0, tzinfo=UTC)
        late.subtotal = 500
        late.shipping = 70
        late.total = 470

        db.add_all([early, late])
        await db.flush()
        db.add_all(
            [
                OrderItem(
                    order_id=early.id,
                    product_id=lamp.id,
                    title=lamp.title,
                    slug=lamp.slug,
                    unit_price=500,
                    quantity=1,
                    line_total=500,
                    regular_price=500,
                    unit_cost=Decimal("10.00"),
                    selection=[],
                ),
                OrderItem(
                    order_id=late.id,
                    product_id=lamp.id,
                    title=lamp.title,
                    slug=lamp.slug,
                    unit_price=500,
                    quantity=1,
                    line_total=400,
                    regular_price=500,
                    unit_cost=None,
                    selection=[],
                ),
            ]
        )
        await db.commit()

        ninth = await sales_summary(
            db, ReportRequest(date_from=date(2026, 11, 9), date_to=date(2026, 11, 9))
        )
        assert ninth.order_count == 1
        assert ninth.units_sold == 1
        assert ninth.gross_sales == 500
        assert ninth.discount == 0
        assert ninth.delivery_charge == 70
        assert ninth.net_sales == 570

        trend = await trend_report(
            db,
            ReportRequest(date_from=date(2026, 11, 9), date_to=date(2026, 11, 10), grain="day"),
            now=datetime(2026, 11, 10, 12, tzinfo=UTC),
        )
        by_day = {point.start: point for point in trend.points}
        assert by_day[date(2026, 11, 9)].net_sales == 570
        assert by_day[date(2026, 11, 9)].profit == Decimal("490.00")
        assert by_day[date(2026, 11, 10)].net_sales == 470
        assert by_day[date(2026, 11, 10)].profit is None
