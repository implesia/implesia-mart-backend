"""Print fields, public tracking lookup, and customer status messages."""

import uuid
from datetime import UTC, date, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.order import ActivityAction, Order, OrderActivity, OrderItem
from app.rate_limit import limiter
from app.services import customer_notify
from app.services.order_admin_service import (
    estimated_delivery_date,
    full_address_of,
    invoice_id_for,
    short_product_id,
)
from tests.test_order_admin import DESK, _enter
from tests.test_orders import SHIPPING, _key, _move
from tests.test_products import _create

_DENIED = {
    "id",
    "email",
    "address",
    "district",
    "area",
    "notes",
    "origin",
    "call_status",
    "manual_discount",
    "paid_amount",
    "payment_status",
    "printed_at",
    "ordered_at",
    "activity",
    "customer_history",
    "duplicate_warning",
    "delivered_at",
    "returned_at",
    "user_id",
    "inventory_held",
    "channel",
    "payment_reference",
    "anonymous",
    "customer_sms_confirmed_at",
    "customer_sms_shipped_at",
    "telegram_notified_at",
    "unit_cost",
    "invoice_id",
    "full_address",
    "estimated_delivery_date",
}


def _order(**overrides: object) -> Order:
    values: dict[str, object] = {
        "number": "IM-AABBCCDD",
        "source": "direct",
        "customer_name": "Rina Akter",
        "phone": "01700000000",
        "district": "Dhaka",
        "area": "Gulshan",
        "address": "House 1, Road 2",
        "delivery_zone": "inside",
        "subtotal": 1500,
        "shipping": 70,
        "total": 1570,
        "due_amount": 1570,
        "created_at": datetime(2026, 11, 1, 6, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return Order(**values)  # type: ignore[arg-type]


def test_invoice_id_is_derived_from_the_order_number() -> None:
    assert invoice_id_for("IM-AB12CD34") == "INV-AB12CD34"
    assert invoice_id_for("IM-AB12CD34") == invoice_id_for("IM-AB12CD34")
    assert invoice_id_for("OTHER") == "INV-OTHER"


def test_estimated_delivery_uses_the_zone_and_does_not_touch_the_total(
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(settings, "delivery_days_inside_dhaka", 2)  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "delivery_days_outside_dhaka", 5)  # type: ignore[attr-defined]
    inside = _order()
    assert estimated_delivery_date(inside) == date(2026, 11, 3)
    assert inside.total == 1570
    suburban = _order(delivery_zone="suburban")
    assert estimated_delivery_date(suburban) == date(2026, 11, 3)
    outside = _order(delivery_zone="outside")
    assert estimated_delivery_date(outside) == date(2026, 11, 6)
    # 18:00 UTC is the next calendar day in Dhaka.
    rolled = _order(created_at=datetime(2026, 11, 1, 18, 0, tzinfo=UTC))
    assert estimated_delivery_date(rolled) == date(2026, 11, 4)
    dated = _order(ordered_at=datetime(2026, 11, 4, 6, 0, tzinfo=UTC))
    assert estimated_delivery_date(dated) == date(2026, 11, 6)
    monkeypatch.setattr(settings, "delivery_days_inside_dhaka", 9)  # type: ignore[attr-defined]
    assert estimated_delivery_date(inside) == date(2026, 11, 10)
    assert inside.total == 1570
    assert full_address_of(_order(address="  House 1 ", area="", district="Dhaka")) == (
        "House 1, Dhaka"
    )
    product_id = uuid.UUID("123e4567-e89b-12d3-a456-426614174000")
    assert short_product_id(product_id) == "123e4567"
    assert short_product_id(None) == ""


def test_messages_are_short_bengali_and_omit_the_phone(monkeypatch: object) -> None:
    monkeypatch.setattr(settings, "admin_base_url", "https://implesia.com")  # type: ignore[attr-defined]
    order = _order(courier_name="Pathao", tracking_number="TRK9", status="shipped")
    confirmed = customer_notify.build_message(order, "confirmed")
    assert "নিশ্চিত" in confirmed
    assert "IM-AABBCCDD" in confirmed
    assert "৳1570" in confirmed
    assert "https://implesia.com/order-status?number=IM-AABBCCDD" in confirmed
    assert order.phone not in confirmed
    shipped = customer_notify.build_message(order, "shipped")
    assert "পাঠানো হয়েছে" in shipped
    assert "Pathao" in shipped
    assert "TRK9" in shipped
    assert order.phone not in shipped
    monkeypatch.setattr(settings, "admin_base_url", "")  # type: ignore[attr-defined]
    bare = customer_notify.build_message(order, "confirmed")
    assert "http" not in bare
    assert "স্ট্যাটাস" not in bare


async def test_log_provider_hides_the_full_phone(monkeypatch: object) -> None:
    seen: list[dict[str, object]] = []

    def info(event: str, **kwargs: object) -> None:
        seen.append({"event": event, **kwargs})

    monkeypatch.setattr(customer_notify.logger, "info", info)  # type: ignore[attr-defined]
    result = await customer_notify.LogCustomerMessageProvider().send(
        phone="01700000000", text="Implesia: অর্ডার IM-AABBCCDD নিশ্চিত।"
    )
    assert result == "logged"
    assert seen[0]["phone_tail"] == "0000"
    assert seen[0]["message"] == "Implesia: অর্ডার IM-AABBCCDD নিশ্চিত।"
    assert "01700000000" not in seen[0].values()
    skipped = await customer_notify.NoopCustomerMessageProvider().send(
        phone="01700000000", text="hidden"
    )
    assert skipped == "skipped"
    assert len(seen) == 1


class _Keep:
    """Hand the request session to the background writer without opening another."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _enable(monkeypatch: object, *, base: str = "https://implesia.com") -> None:
    monkeypatch.setattr(settings, "customer_sms_enabled", True)  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "customer_sms_on_confirmed", True)  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "customer_sms_on_shipped", True)  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "customer_sms_provider", "log")  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "admin_base_url", base)  # type: ignore[attr-defined]


async def test_print_data_adds_invoice_customer_and_item_fields(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(settings, "delivery_days_inside_dhaka", 2)  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "delivery_days_outside_dhaka", 5)  # type: ignore[attr-defined]
    product = await _create(client, auth_headers, title="Print lamp", price=500, quantity=5)
    body = await _enter(
        client,
        auth_headers,
        product["id"],
        email="karim@example.com",
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=0,
        delivery_charge=0,
        paid_amount=0,
        payment_method="cash",
        order_date="2026-11-01",
        phone="01800000071",
    )
    item = (
        await db_session.execute(
            select(OrderItem).where(OrderItem.order_id == uuid.UUID(body["id"]))
        )
    ).scalar_one()
    item.sku = "LAMP-1"
    item.selection = [{"name": "রঙ", "label": "নীল", "swatch": ""}]
    await db_session.commit()
    await client.patch(
        f"{DESK}/{body['id']}",
        headers=auth_headers,
        json={"courier_name": "Pathao", "tracking_number": "TRK-71"},
    )
    slips = await client.post(
        f"{DESK}/print-data",
        headers=auth_headers,
        json={"ids": [body["id"]]},
    )
    assert slips.status_code == 200, slips.text
    printed = slips.json()["orders"][0]
    assert printed["invoice_id"] == "INV-" + body["number"].removeprefix("IM-")
    assert printed["order_number"] == printed["number"] == body["number"]
    assert printed["created_at"]
    assert printed["estimated_delivery_date"] == "2026-11-03"
    assert printed["customer_name"] == "Karim Uddin"
    assert printed["phone"] == "01800000071"
    assert printed["email"] == "karim@example.com"
    assert printed["full_address"] == "House 4, Road 12, Gulshan, Gulshan, Dhaka"
    assert printed["courier_name"] == "Pathao"
    assert printed["tracking_number"] == "TRK-71"
    line = printed["items"][0]
    assert line["title"] == "Print lamp"
    assert line["variant_label"] == "নীল"
    assert line["sku"] == "LAMP-1"
    assert line["product_id_short"] == uuid.UUID(product["id"]).hex[:8]
    assert line["quantity"] == 1
    assert line["unit_price"] == 500
    assert line["line_total"] == 500
    assert printed["total"] == body["total"]
    assert printed["due_amount"] == body["due_amount"]

    monkeypatch.setattr(settings, "delivery_days_inside_dhaka", 4)  # type: ignore[attr-defined]
    again = await client.post(
        f"{DESK}/print-data", headers=auth_headers, json={"ids": [body["id"]]}
    )
    revised = again.json()["orders"][0]
    assert revised["estimated_delivery_date"] == "2026-11-05"
    assert revised["total"] == printed["total"]
    assert revised["subtotal"] == printed["subtotal"]

    outside = await _enter(
        client,
        auth_headers,
        product["id"],
        district="চট্টগ্রাম",
        area="আগ্রাবাদ",
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=0,
        delivery_charge=0,
        paid_amount=0,
        order_date="2026-11-01",
        phone="01800000072",
    )
    outside_slip = await client.post(
        f"{DESK}/print-data", headers=auth_headers, json={"ids": [outside["id"]]}
    )
    assert outside_slip.json()["orders"][0]["estimated_delivery_date"] == "2026-11-06"
    assert outside_slip.json()["orders"][0]["total"] == outside["total"]

    suburban = await _enter(
        client,
        auth_headers,
        product["id"],
        area="Savar",
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=0,
        delivery_charge=0,
        paid_amount=0,
        order_date="2026-11-01",
        phone="01800000073",
    )
    suburban_slip = await client.post(
        f"{DESK}/print-data", headers=auth_headers, json={"ids": [suburban["id"]]}
    )
    assert suburban_slip.json()["orders"][0]["estimated_delivery_date"] == "2026-11-05"


async def test_public_lookup_accepts_tracking_id_and_phone(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    product = await _create(client, auth_headers, title="Track gown", price=900, quantity=4)
    placed = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 1}],
            **SHIPPING,
            "email": "rina@example.com",
        },
    )
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["id"]
    number = placed.json()["number"]
    item = (
        await db_session.execute(select(OrderItem).where(OrderItem.order_id == uuid.UUID(order_id)))
    ).scalar_one()
    item.selection = [{"name": "Size", "label": "M", "swatch": ""}]
    await db_session.commit()
    moved = await client.patch(
        f"/api/v1/admin/orders/{order_id}",
        headers=auth_headers,
        json={"status": "confirmed", "courier_name": "Pathao", "tracking_number": "Pathao-9"},
    )
    assert moved.status_code == 200, moved.text

    by_number = await client.post(
        "/api/v1/orders/lookup",
        json={"number": number, "phone": "01700000000"},
    )
    by_tracking = await client.post(
        "/api/v1/orders/lookup",
        json={"tracking_number": "  pathao-9 ", "phone": "01700-000000"},
    )
    assert by_number.status_code == 200, by_number.text
    assert by_tracking.status_code == 200, by_tracking.text
    assert by_tracking.json()["number"] == number
    body = by_tracking.json()
    assert body["status"] == "confirmed"
    assert body["courier_name"] == "Pathao"
    assert body["tracking_number"] == "Pathao-9"
    assert body["due_amount"] == body["total"]
    assert body["subtotal"] + body["shipping"] == body["total"]
    assert body["items"][0]["title"] == "Track gown"
    assert body["items"][0]["variant_label"] == "M"
    assert body["items"][0]["quantity"] == 1
    assert [event["status"] for event in body["timeline"]] == ["new", "confirmed"]
    assert body["timeline"][0]["at"]
    assert set(body["timeline"][0]) == {"status", "at"}
    assert _DENIED.isdisjoint(body)
    assert "unit_cost" not in body["items"][0]
    assert "email" not in body
    assert "address" not in body

    wrong_phone = await client.post(
        "/api/v1/orders/lookup",
        json={"tracking_number": "Pathao-9", "phone": "01800000000"},
    )
    unknown = await client.post(
        "/api/v1/orders/lookup",
        json={"tracking_number": "NO-SUCH", "phone": "01700000000"},
    )
    assert wrong_phone.status_code == 404
    assert unknown.status_code == 404
    assert wrong_phone.json()["error"]["message"] == unknown.json()["error"]["message"]

    both = await client.post(
        "/api/v1/orders/lookup",
        json={"number": number, "tracking_number": "Pathao-9", "phone": "01700000000"},
    )
    neither = await client.post("/api/v1/orders/lookup", json={"phone": "01700000000"})
    assert both.status_code == 422
    assert neither.status_code == 422

    older = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 1}],
            **SHIPPING,
            "phone": "01900000091",
        },
    )
    assert older.status_code == 201, older.text
    shared = (
        await db_session.execute(select(Order).where(Order.id == uuid.UUID(older.json()["id"])))
    ).scalar_one()
    shared.tracking_number = "Pathao-9"
    await db_session.commit()
    other_phone = await client.post(
        "/api/v1/orders/lookup",
        json={"tracking_number": "Pathao-9", "phone": "01900000091"},
    )
    assert other_phone.status_code == 200
    assert other_phone.json()["number"] == older.json()["number"]
    still_rina = await client.post(
        "/api/v1/orders/lookup",
        json={"tracking_number": "Pathao-9", "phone": "01700000000"},
    )
    assert still_rina.json()["number"] == number


def test_lookup_route_uses_the_public_lookup_limit() -> None:
    limits = limiter._route_limits["app.api.v1.endpoints.orders.lookup_order"]
    assert any(item.limit.amount == 30 and item.limit.GRANULARITY[1] == "minute" for item in limits)


async def test_lookup_is_rate_limited(client: AsyncClient, monkeypatch: object) -> None:
    monkeypatch.setattr(limiter, "enabled", True)  # type: ignore[attr-defined]
    limiter._storage.reset()
    body = {"number": "IM-00000000", "phone": "01700000000"}
    last = None
    for _ in range(30):
        last = await client.post("/api/v1/orders/lookup", json=body)
        assert last.status_code == 404
    blocked = await client.post("/api/v1/orders/lookup", json=body)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    limiter._storage.reset()


async def test_customer_sms_on_confirm_and_ship_is_idempotent(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: object,
) -> None:
    _enable(monkeypatch)
    queued: list[tuple[str, str, str]] = []

    async def spy(order_id: uuid.UUID, number: str, status: str, phone: str, text: str) -> None:
        del order_id, number
        queued.append((status, phone, text))

    monkeypatch.setattr(customer_notify, "deliver", spy)  # type: ignore[attr-defined]
    product = await _create(client, auth_headers, title="SMS lamp", price=500, quantity=4)
    offline = await _enter(
        client,
        auth_headers,
        product["id"],
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=0,
        delivery_charge=0,
        paid_amount=100,
        payment_method="cash",
        phone="01800000081",
    )
    assert offline["due_amount"] == offline["total"] - 100
    confirmed = await _move(client, auth_headers, offline["id"], "confirmed")
    assert confirmed.status_code == 200, confirmed.text
    assert len(queued) == 1
    status, phone, text = queued[0]
    assert status == "confirmed"
    assert phone == "01800000081"
    assert offline["number"] in text
    assert f"৳{offline['total']}" in text
    assert f"৳{offline['due_amount']}" in text
    assert "নিশ্চিত" in text
    assert "https://implesia.com/order-status?number=" in text
    assert phone not in text
    again = await _move(client, auth_headers, offline["id"], "confirmed")
    assert again.status_code == 200
    assert len(queued) == 1
    packed = await _move(client, auth_headers, offline["id"], "packed")
    assert packed.status_code == 200
    assert len(queued) == 1
    shipped = await client.patch(
        f"{DESK}/{offline['id']}",
        headers=auth_headers,
        json={"status": "shipped", "courier_name": "Sundarban", "tracking_number": "SB-81"},
    )
    assert shipped.status_code == 200, shipped.text
    assert len(queued) == 2
    assert queued[1][0] == "shipped"
    assert "Sundarban" in queued[1][2]
    assert "SB-81" in queued[1][2]
    assert "পাঠানো হয়েছে" in queued[1][2]
    db_session.expire_all()
    row = await db_session.get(Order, uuid.UUID(offline["id"]))
    assert row is not None
    assert row.customer_sms_confirmed_at is not None
    assert row.customer_sms_shipped_at is not None
    assert row.total == offline["total"]

    online = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 1}],
            **SHIPPING,
            "phone": "01700000082",
        },
    )
    assert online.status_code == 201, online.text
    bulk = await client.post(
        f"{DESK}/bulk-status",
        headers=auth_headers,
        json={"status": "confirmed", "ids": [online.json()["id"]]},
    )
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["results"][0]["ok"] is True
    assert any(item[1] == "01700000082" and item[0] == "confirmed" for item in queued)


async def test_customer_sms_failure_does_not_block_the_status_change(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: object,
) -> None:
    _enable(monkeypatch)
    calls = {"n": 0}

    class Boom:
        name = "log"

        async def send(self, *, phone: str, text: str) -> str:
            del phone, text
            calls["n"] += 1
            raise RuntimeError("gateway down")

    monkeypatch.setattr(customer_notify, "get_provider", lambda: Boom())  # type: ignore[attr-defined]
    monkeypatch.setattr(customer_notify, "session_factory", lambda: _Keep(db_session))  # type: ignore[attr-defined]
    product = await _create(client, auth_headers, title="SMS fail", price=500, quantity=2)
    body = await _enter(
        client,
        auth_headers,
        product["id"],
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=0,
        delivery_charge=0,
        paid_amount=0,
        phone="01800000083",
    )
    moved = await _move(client, auth_headers, body["id"], "confirmed")
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "confirmed"
    assert calls["n"] == 1
    db_session.expire_all()
    activity = (
        (
            await db_session.execute(
                select(OrderActivity).where(
                    OrderActivity.order_id == uuid.UUID(body["id"]),
                    OrderActivity.action == ActivityAction.CUSTOMER_MESSAGE.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(activity) == 1
    assert activity[0].detail["result"] == "failed"
    assert activity[0].detail["provider"] == "log"
    assert activity[0].detail["status"] == "confirmed"
    assert "phone" not in activity[0].detail
    loaded = await db_session.get(Order, uuid.UUID(body["id"]))
    assert loaded is not None
    from starlette.background import BackgroundTasks

    again = BackgroundTasks()
    await customer_notify.schedule(db_session, again, loaded, "confirmed")
    assert again.tasks == []
    assert calls["n"] == 1


async def test_customer_sms_stays_off_without_the_flag_or_a_phone(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: object,
) -> None:
    queued: list[str] = []

    async def spy(*_args: object, **_kwargs: object) -> None:
        queued.append("sent")

    monkeypatch.setattr(customer_notify, "deliver", spy)  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "customer_sms_enabled", False)  # type: ignore[attr-defined]
    product = await _create(client, auth_headers, title="SMS off", price=500, quantity=3)
    silent = await _enter(
        client,
        auth_headers,
        product["id"],
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=0,
        delivery_charge=0,
        paid_amount=0,
        phone="01800000084",
    )
    assert (await _move(client, auth_headers, silent["id"], "confirmed")).status_code == 200
    assert queued == []
    db_session.expire_all()
    row = await db_session.get(Order, uuid.UUID(silent["id"]))
    assert row is not None
    assert row.customer_sms_confirmed_at is None

    _enable(monkeypatch)
    blank = await _enter(
        client,
        auth_headers,
        product["id"],
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
        manual_discount=0,
        delivery_charge=0,
        paid_amount=0,
        phone="01800000085",
    )
    stored = await db_session.get(Order, uuid.UUID(blank["id"]))
    assert stored is not None
    stored.phone = ""
    await db_session.commit()
    assert (await _move(client, auth_headers, blank["id"], "confirmed")).status_code == 200
    assert queued == []
    db_session.expire_all()
    stored = await db_session.get(Order, uuid.UUID(blank["id"]))
    assert stored is not None
    assert stored.customer_sms_confirmed_at is None
    assert stored.status == "confirmed"


async def test_deliver_records_a_logged_result(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: object,
) -> None:
    monkeypatch.setattr(customer_notify, "session_factory", lambda: _Keep(db_session))  # type: ignore[attr-defined]
    product = await _create(client, auth_headers, title="SMS log", price=400, quantity=1)
    body = await _enter(
        client,
        auth_headers,
        product["id"],
        items=[{"product_id": product["id"], "quantity": 1, "unit_price": 400}],
        manual_discount=0,
        delivery_charge=0,
        paid_amount=0,
        phone="01800000086",
    )
    await customer_notify.deliver(
        uuid.UUID(body["id"]),
        body["number"],
        "confirmed",
        "01800000086",
        "Implesia: অর্ডার নিশ্চিত।",
    )
    db_session.expire_all()
    row = (
        (
            await db_session.execute(
                select(OrderActivity).where(OrderActivity.order_id == uuid.UUID(body["id"]))
            )
        )
        .scalars()
        .all()
    )
    logged = [item for item in row if item.action == ActivityAction.CUSTOMER_MESSAGE.value]
    assert len(logged) == 1
    assert logged[0].detail == {
        "status": "confirmed",
        "result": "logged",
        "provider": "log",
    }
    assert logged[0].actor_user_id is None
