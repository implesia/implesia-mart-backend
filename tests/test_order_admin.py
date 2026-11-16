"""Admin orders desk: offline entry, transitions, edits, filters, fraud flags."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem
from tests.test_orders import SHIPPING, _key, _move, _stock
from tests.test_products import _create

DESK = "/api/v1/admin/orders"


def _offline(product_id: str, **overrides: object) -> dict:
    body: dict = {
        "customer_name": "Karim Uddin",
        "phone": "01800000000",
        "email": "",
        "district": "Dhaka",
        "area": "Gulshan",
        "address": "House 4, Road 12, Gulshan",
        "notes": "Counter sale",
        "items": [{"product_id": product_id, "quantity": 2, "unit_price": 500}],
        "manual_discount": 100,
        "delivery_charge": 80,
        "payment_method": "cash",
        "paid_amount": 200,
    }
    body.update(overrides)
    return body


async def _enter(
    client: AsyncClient, headers: dict[str, str], product_id: str, **overrides: object
) -> dict:
    response = await client.post(
        f"{DESK}/offline",
        headers={**headers, "Idempotency-Key": _key()},
        json=_offline(product_id, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_offline_order_prices_stock_and_skips_tracking(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    product = await _create(
        client, auth_headers, title="Counter lamp", price=900, quantity=5, cost_price="40.00"
    )
    with (
        patch("app.services.order_service.meta_capi.schedule_purchase") as purchase,
        patch(
            "app.services.order_service.telegram_notify.notify_new_order",
            new_callable=AsyncMock,
        ) as notified,
    ):
        body = await _enter(client, auth_headers, product["id"])
        assert purchase.call_count == 0
        assert notified.await_count == 0
        online = await client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": _key()},
            json={
                "source": "direct",
                "items": [{"product_id": product["id"], "quantity": 1}],
                **SHIPPING,
                "phone": "01900000000",
            },
        )
        assert online.status_code == 201, online.text
        assert "origin" not in online.json()
        assert purchase.call_count == 1
        assert notified.await_count == 1

    assert body["origin"] == "offline"
    assert body["source"] == "direct"
    assert body["status"] == "new"
    assert body["payment_method"] == "cash"
    assert body["payment_status"] == "partial"
    assert body["items"][0]["unit_price"] == 500
    assert body["items"][0]["line_total"] == 1000
    assert body["subtotal"] == 1000
    assert body["manual_discount"] == 100
    assert body["shipping"] == 80
    assert body["total"] == 980
    assert body["paid_amount"] == 200
    assert body["due_amount"] == 780
    assert body["analytics_event_id"] == f"purchase_{body['number']}"
    assert any(row["action"] == "created" for row in body["activity"])
    stored = (
        await db_session.execute(
            select(OrderItem).where(OrderItem.order_id == uuid.UUID(body["id"]))
        )
    ).scalar_one()
    assert stored.unit_cost is not None
    assert Decimal(str(stored.unit_cost)) == Decimal("40.00")
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 2


async def test_offline_blocks_when_stock_is_short_and_replays(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Last lamp", price=500, quantity=1)
    rejected = await client.post(
        f"{DESK}/offline",
        headers={**auth_headers, "Idempotency-Key": _key()},
        json=_offline(product["id"], items=[{"product_id": product["id"], "quantity": 2}]),
    )
    assert rejected.status_code == 422
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 1

    key = _key()
    first = await client.post(
        f"{DESK}/offline",
        headers={**auth_headers, "Idempotency-Key": key},
        json=_offline(
            product["id"],
            items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
            manual_discount=0,
            paid_amount=500,
        ),
    )
    assert first.status_code == 201, first.text
    again = await client.post(
        f"{DESK}/offline",
        headers={**auth_headers, "Idempotency-Key": key},
        json=_offline(
            product["id"],
            items=[{"product_id": product["id"], "quantity": 1, "unit_price": 1}],
            paid_amount=0,
        ),
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["total"] == first.json()["total"]
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 0


async def test_item_edit_before_confirm_adjusts_stock_and_totals(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Editable lamp", price=500, quantity=5)
    body = await _enter(client, auth_headers, product["id"])
    edited = await client.put(
        f"{DESK}/{body['id']}/items",
        headers=auth_headers,
        json={
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 400}],
        },
    )
    assert edited.status_code == 200, edited.text
    saved = edited.json()
    assert saved["items"][0]["quantity"] == 1
    assert saved["items"][0]["unit_price"] == 400
    assert saved["subtotal"] == 400
    assert saved["manual_discount"] == 100
    assert saved["total"] == 380
    assert saved["due_amount"] == 180
    assert any(row["action"] == "items_edited" for row in saved["activity"])
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 4

    confirmed = await _move(client, auth_headers, body["id"], "confirmed")
    assert confirmed.status_code == 200, confirmed.text
    blocked = await client.put(
        f"{DESK}/{body['id']}/items",
        headers=auth_headers,
        json={"items": [{"product_id": product["id"], "quantity": 1, "unit_price": 100}]},
    )
    assert blocked.status_code == 422
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 4


async def test_cancel_and_return_put_stock_back(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Restock lamp", price=500, quantity=4)
    cancelled = await _enter(
        client,
        auth_headers,
        product["id"],
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=0,
        paid_amount=0,
        phone="01800000011",
    )
    assert (await _move(client, auth_headers, cancelled["id"], "cancelled")).status_code == 200
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 4

    returned = await _enter(
        client,
        auth_headers,
        product["id"],
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=0,
        paid_amount=500,
        phone="01800000012",
    )
    for status in ("confirmed", "packed", "shipped", "delivered", "returned"):
        moved = await _move(client, auth_headers, returned["id"], status)
        assert moved.status_code == 200, moved.text
    assert (await _stock(client, auth_headers, product["id"]))["quantity"] == 4
    skipped = await _move(client, auth_headers, returned["id"], "shipped")
    assert skipped.status_code == 409


async def test_bulk_status_keeps_the_successes(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Bulk lamp", price=500, quantity=4)
    ready = await _enter(client, auth_headers, product["id"], phone="01800000021")
    waiting = await _enter(client, auth_headers, product["id"], phone="01800000022")
    assert (await _move(client, auth_headers, ready["id"], "confirmed")).status_code == 200
    assert (await _move(client, auth_headers, ready["id"], "packed")).status_code == 200
    missing = str(uuid.uuid4())
    result = await client.post(
        f"{DESK}/bulk-status",
        headers=auth_headers,
        json={"status": "shipped", "ids": [ready["id"], waiting["id"], missing]},
    )
    assert result.status_code == 200, result.text
    by_id = {row["id"]: row for row in result.json()["results"]}
    assert by_id[ready["id"]]["ok"] is True
    assert by_id[ready["id"]]["status"] == "shipped"
    assert by_id[waiting["id"]]["ok"] is False
    assert by_id[missing]["ok"] is False
    still = await client.get(f"{DESK}/{waiting['id']}", headers=auth_headers)
    assert still.json()["status"] == "new"


async def test_filters_history_and_duplicate_warning(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    product = await _create(client, auth_headers, title="Filter lamp", price=500, quantity=6)
    phone = "01800000031"
    older = await _enter(client, auth_headers, product["id"], phone=phone, customer_name="Nabila")
    await db_session.execute(
        update(Order)
        .where(Order.id == uuid.UUID(older["id"]))
        .values(created_at=datetime.now(UTC) - timedelta(days=3))
    )
    await db_session.commit()
    recent = await _enter(client, auth_headers, product["id"], phone=phone, customer_name="Nabila")
    detail = await client.get(f"{DESK}/{recent['id']}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["duplicate_warning"] is False
    assert detail.json()["customer_history"]["total_orders"] == 2

    burst = await _enter(client, auth_headers, product["id"], phone=phone, customer_name="Nabila")
    warned = await client.get(f"{DESK}/{burst['id']}", headers=auth_headers)
    assert warned.json()["duplicate_warning"] is True
    assert warned.json()["customer_history"]["total_orders"] == 3

    marked = await client.patch(
        f"{DESK}/{burst['id']}",
        headers=auth_headers,
        json={"call_status": "fake", "courier_name": "Pathao", "tracking_number": "P-1"},
    )
    assert marked.status_code == 200, marked.text
    actions = {row["action"] for row in marked.json()["activity"]}
    assert "call_status_changed" in actions
    assert "courier_edited" in actions

    found = await client.get(
        DESK,
        headers=auth_headers,
        params={"origin": "offline", "call_status": "fake", "payment_method": "cash", "q": phone},
    )
    assert found.status_code == 200, found.text
    ids = {item["id"] for item in found.json()["items"]}
    assert ids == {burst["id"]}
    counts = found.json()["status_counts"]
    assert counts["new"] == 1
    assert sum(counts.values()) == 1

    customers = await client.get(f"{DESK}/customers", headers=auth_headers, params={"q": "Nabila"})
    assert customers.status_code == 200, customers.text
    assert customers.json()["items"][0]["phone"] == phone
    assert customers.json()["items"][0]["orders"] == 3


async def test_pack_queue_print_and_overview(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(client, auth_headers, title="Pack lamp", price=500, quantity=3)
    body = await _enter(
        client,
        auth_headers,
        product["id"],
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=50,
        delivery_charge=0,
        paid_amount=0,
        payment_method="due",
        phone="01800000041",
    )
    assert (await _move(client, auth_headers, body["id"], "packed")).status_code == 409
    assert (await _move(client, auth_headers, body["id"], "confirmed")).status_code == 200
    queue = await client.get(f"{DESK}/ready-to-pack", headers=auth_headers)
    assert queue.status_code == 200, queue.text
    assert body["id"] in {item["id"] for item in queue.json()["items"]}
    assert all(item["status"] == "confirmed" for item in queue.json()["items"])

    slips = await client.post(
        f"{DESK}/print-data",
        headers=auth_headers,
        json={"ids": [body["id"], str(uuid.uuid4())]},
    )
    assert slips.status_code == 200, slips.text
    printed_order = slips.json()["orders"][0]
    assert printed_order["number"] == body["number"]
    assert printed_order["due_amount"] == 450
    assert printed_order["payment_status"] == "unpaid"
    assert printed_order["items"][0]["quantity"] == 1
    assert len(slips.json()["missing"]) == 1

    first = await client.post(
        f"{DESK}/printed", headers=auth_headers, json={"ids": [body["id"]]}
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"{DESK}/printed", headers=auth_headers, json={"ids": [body["id"]]}
    )
    detail = await client.get(f"{DESK}/{body['id']}", headers=auth_headers)
    prints = [row for row in detail.json()["activity"] if row["action"] == "printed"]
    assert len(prints) == 2
    assert body["id"] in second.json()["printed"]
    assert detail.json()["printed_at"] is not None

    overview = await client.get(f"{DESK}/overview", headers=auth_headers)
    assert overview.status_code == 200, overview.text
    board = overview.json()
    assert board["pending_confirm"] >= 0
    assert board["ready_to_pack"] >= 1
    assert {row["origin"] for row in board["origins"]} == {"online", "offline"}
    assert set(board["status_counts"]) == {
        "new",
        "confirmed",
        "packed",
        "shipped",
        "delivered",
        "cancelled",
        "returned",
    }
    assert board["today"]["orders"] >= 1


async def test_delivered_offline_order_is_in_sales(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    product = await _create(
        client, auth_headers, title="Reported lamp", price=500, quantity=2, cost_price="10.00"
    )
    body = await _enter(
        client,
        auth_headers,
        product["id"],
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=50,
        delivery_charge=0,
        paid_amount=450,
        payment_method="bkash",
        phone="01800000051",
    )
    for status in ("confirmed", "packed", "shipped", "delivered"):
        moved = await _move(client, auth_headers, body["id"], status)
        assert moved.status_code == 200, moved.text
    sales = await client.get(
        "/api/v1/admin/reports/sales",
        headers=auth_headers,
        params={"preset": "this_month"},
    )
    assert sales.status_code == 200, sales.text
    assert sales.json()["order_count"] == 1
    assert sales.json()["net_sales"] == 450
    assert sales.json()["coupon_discount"] == 0
    assert sales.json()["discount"] == 50
