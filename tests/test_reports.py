"""Sales reports: Dhaka dates, delivered_at, unknown cost, return rate, Excel."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO

from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import StockMovement
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.services.report_service import window_bounds
from app.services.shop_sql import SHOP
from tests.test_orders import SHIPPING, _key, _move
from tests.test_products import _create


def test_presets_follow_the_dhaka_calendar() -> None:
    # Tuesday 10 Nov 2026, 23:30 in Dhaka. The week starts Monday.
    evening = datetime(2026, 11, 10, 23, 30, tzinfo=SHOP)
    _preset, start, end, _open, _close = window_bounds(
        preset="this_week", date_from=None, date_to=None, now=evening
    )
    assert (start, end) == (date(2026, 11, 9), date(2026, 11, 10))

    _preset, start, end, _open, _close = window_bounds(
        preset="this_month", date_from=None, date_to=None, now=evening
    )
    assert (start, end) == (date(2026, 11, 1), date(2026, 11, 10))

    _preset, start, end, _open, _close = window_bounds(
        preset="last_month", date_from=None, date_to=None, now=evening
    )
    assert (start, end) == (date(2026, 10, 1), date(2026, 10, 31))

    # 18:30 UTC on the 9th is 00:30 on the 10th in Dhaka, so "today" is the 10th.
    just_after_midnight = datetime(2026, 11, 9, 18, 30, tzinfo=UTC)
    _preset, start, end, opened, closed = window_bounds(
        preset="this_week", date_from=None, date_to=None, now=just_after_midnight
    )
    assert (start, end) == (date(2026, 11, 9), date(2026, 11, 10))
    assert opened == datetime(2026, 11, 9, 0, 0, tzinfo=SHOP)
    assert closed == datetime(2026, 11, 11, 0, 0, tzinfo=SHOP)


async def _place(
    client: AsyncClient, product_id: str, quantity: int, *, phone: str = "01700000000"
) -> dict:
    response = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product_id, "quantity": quantity}],
            **SHIPPING,
            "phone": phone,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _deliver(client: AsyncClient, headers: dict[str, str], order_id: str) -> None:
    for status in ("confirmed", "packed", "shipped", "delivered"):
        moved = await _move(client, headers, order_id, status)
        assert moved.status_code == 200, moved.text


async def _stamp(db: AsyncSession, order_id: str, **values: object) -> None:
    await db.execute(update(Order).where(Order.id == uuid.UUID(order_id)).values(**values))
    await db.commit()


def _gross(item: dict) -> int:
    regular = item["regular_price"] if item["regular_price"] is not None else item["unit_price"]
    return int(regular) * int(item["quantity"])


async def test_reports_count_delivered_at_and_keep_unknown_cost(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    known = await _create(
        client, auth_headers, title="Known lamp", price=500, quantity=10, cost_price="40.50"
    )
    unknown = await _create(
        client, auth_headers, title="Unknown lamp", price=200, quantity=10
    )
    idle = await _create(
        client, auth_headers, title="Idle cup", price=100, quantity=2, cost_price="10.00"
    )

    early = await _place(client, known["id"], 2, phone="01711111111")
    boundary = await _place(client, unknown["id"], 1, phone="01822222222")
    pending = await _place(client, known["id"], 1, phone="01933333333")
    returned = await _place(client, known["id"], 1, phone="01644444444")
    cancelled = await _place(client, known["id"], 1, phone="01555555555")

    assert "unit_cost" not in early
    assert "cost_price" not in early
    assert all("unit_cost" not in item for item in early["items"])
    public = await client.get(f"/api/v1/products/{known['id']}")
    assert public.status_code == 200, public.text
    assert "cost_price" not in public.json()
    assert "unit_cost" not in public.text

    stored = await db_session.scalar(
        select(OrderItem.unit_cost).where(OrderItem.order_id == uuid.UUID(early["id"]))
    )
    assert stored == Decimal("40.50")
    channel = await db_session.scalar(
        select(Order.channel).where(Order.id == uuid.UUID(early["id"]))
    )
    assert channel == "website"

    await _deliver(client, auth_headers, early["id"])
    await _deliver(client, auth_headers, boundary["id"])
    await _deliver(client, auth_headers, returned["id"])
    sent_back = await _move(client, auth_headers, returned["id"], "returned")
    assert sent_back.status_code == 200, sent_back.text
    dropped = await _move(client, auth_headers, cancelled["id"], "cancelled")
    assert dropped.status_code == 200, dropped.text

    # Early was placed in January and delivered just before Dhaka midnight.
    # The 18:00 UTC stamp is 00:00 on 10 Nov in Dhaka, so it belongs to the 10th.
    await _stamp(
        db_session,
        early["id"],
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        delivered_at=datetime(2026, 11, 9, 17, 59, tzinfo=UTC),
    )
    await _stamp(
        db_session,
        boundary["id"],
        delivered_at=datetime(2026, 11, 9, 18, 0, tzinfo=UTC),
    )
    await _stamp(
        db_session,
        returned["id"],
        delivered_at=datetime(2026, 11, 9, 4, 0, tzinfo=UTC),
        returned_at=datetime(2026, 11, 9, 6, 0, tzinfo=UTC),
    )
    await _stamp(
        db_session,
        cancelled["id"],
        updated_at=datetime(2026, 11, 9, 8, 0, tzinfo=UTC),
    )
    # A later cost change must not rewrite the snapshot.
    await db_session.execute(
        update(Product)
        .where(Product.id == uuid.UUID(known["id"]))
        .values(cost_price=Decimal("99.00"))
    )
    await db_session.commit()

    params = {"from": "2026-11-09", "to": "2026-11-09"}
    sales = await client.get("/api/v1/admin/reports/sales", headers=auth_headers, params=params)
    assert sales.status_code == 200, sales.text
    body = sales.json()
    assert body["filters"]["from"] == "2026-11-09"
    assert body["filters"]["to"] == "2026-11-09"
    assert body["filters"]["timezone"] == "Asia/Dhaka"
    assert body["order_count"] == 1
    # Returned order is excluded from realized sales, units, shipping, COGS, and profit.
    nov9_items = early["items"]
    gross = sum(_gross(item) for item in nov9_items)
    merchandise = sum(item["line_total"] for item in nov9_items)
    shipping = early["shipping"]
    assert body["units_sold"] == 2
    assert body["gross_sales"] == gross
    assert body["discount"] == gross - merchandise
    assert body["coupon_discount"] == 0
    assert body["manual_discount"] == 0
    assert body["delivery_charge"] == shipping
    assert body["net_sales"] == merchandise + shipping
    # The pending order and the order delivered at Dhaka midnight are outside this day.
    assert pending["id"] not in sales.text

    tenth = await client.get(
        "/api/v1/admin/reports/sales",
        headers=auth_headers,
        params={"from": "2026-11-10", "to": "2026-11-10"},
    )
    assert tenth.status_code == 200, tenth.text
    assert tenth.json()["order_count"] == 1
    assert tenth.json()["units_sold"] == 1
    assert tenth.json()["net_sales"] == boundary["total"]

    profit = await client.get("/api/v1/admin/reports/profit", headers=auth_headers, params=params)
    assert profit.status_code == 200, profit.text
    earned = profit.json()
    assert earned["unknown_cost_lines"] == 0
    assert earned["unknown_cost_units"] == 0
    assert earned["cost"] == 81.0
    assert earned["revenue"] == merchandise
    assert earned["profit"] == round(merchandise - 81.0, 2)
    # Current product cost is 99. The report did not use it.

    unknown_profit = await client.get(
        "/api/v1/admin/reports/profit",
        headers=auth_headers,
        params={"from": "2026-11-10", "to": "2026-11-10"},
    )
    assert unknown_profit.status_code == 200, unknown_profit.text
    missing = unknown_profit.json()
    assert missing["cost"] is None
    assert missing["profit"] is None
    assert missing["unknown_cost_units"] == 1
    assert missing["unknown_cost_revenue"] == boundary["items"][0]["line_total"]
    assert missing["revenue"] == 0

    trend = await client.get(
        "/api/v1/admin/reports/trend",
        headers=auth_headers,
        params={"from": "2026-11-08", "to": "2026-11-10", "grain": "day"},
    )
    assert trend.status_code == 200, trend.text
    points = {point["start"]: point for point in trend.json()["points"]}
    assert list(points) == ["2026-11-08", "2026-11-09", "2026-11-10"]
    assert points["2026-11-08"]["net_sales"] == 0
    assert points["2026-11-08"]["profit"] == 0
    assert points["2026-11-09"]["net_sales"] == body["net_sales"]
    assert points["2026-11-09"]["profit"] == earned["profit"]
    assert points["2026-11-10"]["net_sales"] == tenth.json()["net_sales"]
    assert points["2026-11-10"]["profit"] is None

    products = await client.get(
        "/api/v1/admin/reports/products", headers=auth_headers, params=params
    )
    assert products.status_code == 200, products.text
    rows = {row["title"]: row for row in products.json()["items"]}
    assert rows["Known lamp"]["units_sold"] == 2
    assert rows["Known lamp"]["return_count"] == 1
    assert rows["Known lamp"]["return_value"] == returned["items"][0]["line_total"]
    assert rows["Known lamp"]["cost"] == 81.0
    assert "Unknown lamp" not in rows

    delivery = await client.get(
        "/api/v1/admin/reports/delivery", headers=auth_headers, params=params
    )
    assert delivery.status_code == 200, delivery.text
    flow = delivery.json()
    assert flow["delivered"] == 2
    assert flow["returned"] == 1
    assert flow["returned_value"] == returned["total"]
    assert flow["cancelled"] == 1
    assert flow["return_rate_percent"] == 50

    await _stamp(db_session, boundary["id"], channel=None)
    website = await client.get(
        "/api/v1/admin/reports/sales",
        headers=auth_headers,
        params={"from": "2026-11-10", "to": "2026-11-10", "channel": "website"},
    )
    assert website.status_code == 200, website.text
    assert website.json()["order_count"] == 0
    anyone = await client.get(
        "/api/v1/admin/reports/sales",
        headers=auth_headers,
        params={"from": "2026-11-10", "to": "2026-11-10"},
    )
    assert anyone.json()["order_count"] == 1

    exported = await client.get(
        "/api/v1/admin/reports/sales/export",
        headers=auth_headers,
        params={"from": "2026-11-09", "to": "2026-11-10"},
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    book = load_workbook(BytesIO(exported.content), data_only=True)
    sheet = book.active
    assert sheet is not None
    grid = [tuple(row) for row in sheet.iter_rows(values_only=True)]
    flat = [cell for row in grid for cell in row]
    assert "Asia/Dhaka" in flat
    assert "2026-11-09" in flat
    assert "2026-11-10" in flat
    header_at = next(index for index, row in enumerate(grid) if row and row[0] == "Order count")
    headers = grid[header_at]
    values = grid[header_at + 1]
    for column in ("Gross sales", "Discount", "Delivery charge", "Net sales"):
        cell = values[headers.index(column)]
        assert isinstance(cell, (int, float)), column
    both = await client.get(
        "/api/v1/admin/reports/sales",
        headers=auth_headers,
        params={"from": "2026-11-09", "to": "2026-11-10"},
    )
    assert values[headers.index("Net sales")] == both.json()["net_sales"]
    assert values[headers.index("Gross sales")] == both.json()["gross_sales"]

    stock = await client.get(
        "/api/v1/admin/reports/stock",
        headers=auth_headers,
        params={"from": "2026-11-01", "to": "2026-11-10"},
    )
    assert stock.status_code == 200, stock.text
    stock_body = stock.json()
    assert stock_body["period_applies"] is False
    assert stock_body["filters"]["channel_applies"] is False
    by_title = {row["title"]: row for row in stock_body["items"]}
    assert by_title["Idle cup"]["low_stock"] is True
    assert by_title["Idle cup"]["no_sale_30d"] is True
    assert by_title["Idle cup"]["stock_value"] == 20
    assert by_title["Idle cup"]["quantity"] == 2

    ledger_id = uuid.UUID(idle["id"])
    db_session.add_all(
        [
            StockMovement(
                product_id=ledger_id,
                quantity=10,
                movement_type="opening",
                created_at=datetime(2026, 11, 1, 6, 0, tzinfo=UTC),
            ),
            StockMovement(
                product_id=ledger_id,
                quantity=5,
                movement_type="purchase",
                created_at=datetime(2026, 11, 2, 6, 0, tzinfo=UTC),
            ),
            StockMovement(
                product_id=ledger_id,
                quantity=-2,
                movement_type="sale",
                created_at=datetime(2026, 11, 3, 6, 0, tzinfo=UTC),
            ),
        ]
    )
    await db_session.commit()
    movements = await client.get(
        "/api/v1/admin/reports/movements",
        headers=auth_headers,
        params={"from": "2026-11-02", "to": "2026-11-03", "product_id": idle["id"]},
    )
    assert movements.status_code == 200, movements.text
    ledger = movements.json()
    assert ledger["opening_balance"] == 10
    assert ledger["opening"] == 0
    assert ledger["purchase"] == 5
    assert ledger["sale"] == -2
    assert ledger["return"] == 0
    assert ledger["cancel"] == 0
    assert ledger["adjustment"] == 0
    assert ledger["closing"] == 13
    assert ledger["closing"] == (
        ledger["opening_balance"]
        + ledger["opening"]
        + ledger["purchase"]
        + ledger["sale"]
        + ledger["return"]
        + ledger["cancel"]
        + ledger["adjustment"]
    )


async def test_reports_are_staff_reads(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get(
        "/api/v1/admin/reports/sales", params={"from": "2026-11-01", "to": "2026-11-02"}
    )
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "report-viewer@implesia.com",
            "full_name": "Report Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "report-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    allowed = await client.get(
        "/api/v1/admin/reports/delivery",
        headers=headers,
        params={"preset": "this_month"},
    )
    assert allowed.status_code == 200, allowed.text
    refused = await client.post("/api/v1/admin/reports/sales", headers=headers)
    assert refused.status_code == 405

    missing = await client.get("/api/v1/admin/reports/sales", headers=headers)
    assert missing.status_code == 422
    wide = await client.get(
        "/api/v1/admin/reports/trend",
        headers=headers,
        params={"from": "2020-01-01", "to": "2026-11-10"},
    )
    assert wide.status_code == 422
