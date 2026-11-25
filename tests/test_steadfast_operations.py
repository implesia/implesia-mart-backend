"""Tests for Phase 23 Steadfast Merchant API client, courier operations, and public locations."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.courier import CourierShipment
from app.models.order import ActivityAction, Order, OrderActivity, OrderStatus
from app.models.user import UserRole
from app.schemas.user import UserCreate
from app.services import user_service
from app.services.courier.steadfast_client import (
    MAX_INVOICE_LEN,
    MAX_NOTE_LEN,
    MAX_RECIPIENT_ADDRESS_LEN,
    MAX_RECIPIENT_NAME_LEN,
    MAX_RECIPIENT_PHONE_LEN,
    SteadfastAuthError,
    SteadfastCircuitOpenError,
    sanitize_order_payload,
    sanitize_steadfast_text,
    steadfast_client,
)
from app.services.redis_client import redis_client
from tests.conftest import TEST_PASSWORD

BASE_ADMIN = "/api/v1/admin/courier/steadfast"


@pytest.fixture(autouse=True)
def _reset_steadfast_state(monkeypatch: pytest.MonkeyPatch):
    redis_client.reset_memory_state()
    monkeypatch.setattr(settings, "steadfast_api_key", SecretStr("sf-test-key"))
    monkeypatch.setattr(settings, "steadfast_secret_key", SecretStr("sf-test-secret"))
    monkeypatch.setattr(settings, "steadfast_base_url", "https://portal.packzy.com/api/v1")
    monkeypatch.setattr(settings, "steadfast_pickup_address", "House 12, Road 4, Mirpur, Dhaka")
    monkeypatch.setattr(settings, "steadfast_pickup_phone", "01711000000")
    orig_factory = steadfast_client._client_factory
    yield
    steadfast_client._client_factory = orig_factory
    redis_client.reset_memory_state()


def _install_mock(handler: Callable[[httpx.Request], httpx.Response]) -> None:
    transport = httpx.MockTransport(handler)
    steadfast_client._client_factory = lambda timeout: httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
    )


async def _make_order(
    db: AsyncSession,
    *,
    number: str,
    status: str = OrderStatus.CONFIRMED.value,
    total: int = 1500,
    paid_amount: int = 200,
    due_amount: int | None = 1300,
) -> Order:
    order = Order(
        id=uuid.uuid4(),
        number=number,
        source="direct",
        customer_name="Rahim {VIP}; <Test>",
        phone="01712345678",
        district="Dhaka",
        area="Mirpur 10",
        address="House 10; $Block <B>",
        notes="Call before arrival; {fragile}",
        delivery_zone="inside_dhaka",
        subtotal=total - 60,
        shipping=60,
        total=total,
        paid_amount=paid_amount,
        due_amount=due_amount,
        status=status,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


async def _login_role(
    db: AsyncSession,
    client: AsyncClient,
    *,
    email: str,
    role: UserRole,
) -> dict[str, str]:
    await user_service.create_user(
        db,
        UserCreate(
            email=email,
            full_name=f"User {role.value}",
            password=TEST_PASSWORD,
            role=role,
        ),
    )
    if role == UserRole.CUSTOMER:
        res = await client.post(
            "/api/v1/customer/auth/login",
            json={"identifier": email, "password": TEST_PASSWORD},
        )
    else:
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": TEST_PASSWORD},
        )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_sanitizer_strips_forbidden_chars_and_truncates() -> None:
    dirty = "Hello {world}; <script>$alert</script>\nline2\t!"
    cleaned = sanitize_steadfast_text(dirty, 100)
    for ch in ("{", "}", ";", "<", ">", "$", "\n", "\t"):
        assert ch not in cleaned
    assert cleaned == "Hello world script alert /script line2 !"

    payload = sanitize_order_payload(
        {
            "invoice": "INV-" + "A" * 150,
            "recipient_name": "N{a};m<e>" + "B" * 150,
            "recipient_phone": "017" + "1" * 60,
            "recipient_address": "Addr $; " + "C" * 600,
            "note": "Note {x} " + "D" * 600,
            "cod_amount": -50,
            "delivery_type": 1,
        }
    )
    assert len(payload["invoice"]) == MAX_INVOICE_LEN
    assert len(payload["recipient_name"]) == MAX_RECIPIENT_NAME_LEN
    assert len(payload["recipient_phone"]) == MAX_RECIPIENT_PHONE_LEN
    assert len(payload["recipient_address"]) == MAX_RECIPIENT_ADDRESS_LEN
    assert len(payload["note"]) == MAX_NOTE_LEN
    assert payload["cod_amount"] == 0
    assert payload["delivery_type"] == 1


async def test_circuit_breaker_trips_after_three_401s_without_retrying(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    calls = 0

    def always_401(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"message": "Unauthorized"})

    _install_mock(always_401)

    for attempt in range(1, 4):
        with pytest.raises(SteadfastAuthError):
            await steadfast_client.get_balance()
        assert calls == attempt

    # 4th call MUST short-circuit locally without hitting HTTP transport
    with pytest.raises(SteadfastCircuitOpenError):
        await steadfast_client.get_balance()
    assert calls == 3

    # Ping endpoint reports circuit_open=True and does not call upstream
    ping_res = await client.get(f"{BASE_ADMIN}/ping", headers=auth_headers)
    assert ping_res.status_code == 200, ping_res.text
    body = ping_res.json()
    assert body["configured"] is True
    assert body["ok"] is False
    assert body["circuit_open"] is True
    assert body["circuit_retry_after_seconds"] > 0
    assert calls == 3


async def test_ping_success(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/get_balance"
        assert request.headers["api-key"] == "sf-test-key"
        assert request.headers["secret-key"] == "sf-test-secret"
        return httpx.Response(200, json={"status": 200, "current_balance": 12450.5})

    _install_mock(handler)
    res = await client.get(f"{BASE_ADMIN}/ping", headers=auth_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["configured"] is True
    assert data["ok"] is True
    assert data["balance"] == 12450.5
    assert data["circuit_open"] is False


async def test_book_order_duplicate_guard_and_activity_log(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    order = await _make_order(db_session, number="IM-2026-0001")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/create_order"
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "status": 200,
                "message": "Consignment has been created successfully.",
                "consignment": {
                    "consignment_id": 987654,
                    "invoice": "IM-2026-0001",
                    "tracking_code": "SF-TRK-001",
                    "status": "in_review",
                },
            },
        )

    _install_mock(handler)

    res = await client.post(
        f"{BASE_ADMIN}/orders/{order.id}/book",
        headers=auth_headers,
        json={},
    )
    assert res.status_code == 200, res.text
    shipment = res.json()
    assert shipment["consignment_id"] == "987654"
    assert shipment["tracking_code"] == "SF-TRK-001"
    assert shipment["cod_amount"] == 1300
    assert shipment["delivery_status"] == "in_review"

    # Sanitized payload sent to Steadfast
    assert captured["body"]["invoice"] == "IM-2026-0001"
    assert captured["body"]["cod_amount"] == 1300
    assert "{" not in captured["body"]["recipient_name"]
    assert ";" not in captured["body"]["recipient_address"]
    assert "$" not in captured["body"]["recipient_address"]

    # Order updated + activity recorded
    await db_session.refresh(order)
    assert order.courier_name == "Steadfast"
    assert order.tracking_number == "SF-TRK-001"

    activity = await db_session.scalar(
        select(OrderActivity).where(
            OrderActivity.order_id == order.id,
            OrderActivity.action == ActivityAction.COURIER_BOOKED.value,
        )
    )
    assert activity is not None

    # Duplicate booking is rejected with 409
    dup = await client.post(
        f"{BASE_ADMIN}/orders/{order.id}/book",
        headers=auth_headers,
        json={},
    )
    assert dup.status_code == 409


async def test_bulk_book_handles_http200_per_item_errors_and_skips(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    o_ok = await _make_order(db_session, number="IM-BULK-1")
    o_fail = await _make_order(db_session, number="IM-BULK-2")
    o_cancelled = await _make_order(
        db_session, number="IM-BULK-3", status=OrderStatus.CANCELLED.value
    )
    missing_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/create_order/bulk-order/extended"
        body = json.loads(request.content)
        items = body["data"]
        assert [i["invoice"] for i in items] == ["IM-BULK-1", "IM-BULK-2"]
        # Steadfast returns HTTP 200 with per-item errors inside data
        return httpx.Response(
            200,
            json={
                "status": 200,
                "data": [
                    {
                        "invoice": "IM-BULK-1",
                        "consignment_id": 555001,
                        "tracking_code": "SF-BULK-1",
                        "status": "success",
                    },
                    {
                        "invoice": "IM-BULK-2",
                        "status": "error",
                        "errors": {"recipient_phone": ["Invalid phone number"]},
                        "message": "Invalid phone number",
                    },
                ],
            },
        )

    _install_mock(handler)

    res = await client.post(
        f"{BASE_ADMIN}/orders/bulk-book",
        headers=auth_headers,
        json={"order_ids": [str(o_ok.id), str(o_fail.id), str(o_cancelled.id), str(missing_id)]},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["requested"] == 4
    assert data["booked"] == 1
    assert data["failed"] == 1
    assert data["skipped"] == 2

    by_id = {r["order_id"]: r for r in data["results"]}
    assert by_id[str(o_ok.id)]["status"] == "booked"
    assert by_id[str(o_ok.id)]["shipment"]["consignment_id"] == "555001"
    assert by_id[str(o_fail.id)]["status"] == "error"
    assert "recipient_phone" in by_id[str(o_fail.id)]["errors"]
    assert by_id[str(o_cancelled.id)]["status"] == "skipped"
    assert by_id[str(missing_id)]["status"] == "skipped"

    stored = (await db_session.scalars(select(CourierShipment))).all()
    assert len(stored) == 1
    assert stored[0].order_id == o_ok.id


async def test_refresh_status_cooldown_and_final_delivery_sync(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    order = await _make_order(db_session, number="IM-SYNC-1", status=OrderStatus.SHIPPED.value)
    shipment = CourierShipment(
        order_id=order.id,
        provider="steadfast",
        invoice=order.number,
        consignment_id="777888",
        tracking_code="SF-SYNC-1",
        cod_amount=1300,
        delivery_status="in_review",
    )
    db_session.add(shipment)
    await db_session.commit()

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/api/v1/status_with_return_by_cid/777888":
            return httpx.Response(
                200,
                json={"status": 200, "delivery_status": "delivered", "return_status": None},
            )
        if request.url.path == "/api/v1/trackings_by_invoice/IM-SYNC-1":
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "data": [
                        {"status": "in_review", "time": "2026-11-24T10:00:00Z"},
                        {"status": "delivered", "time": "2026-11-25T09:00:00Z"},
                    ],
                },
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    _install_mock(handler)

    first = await client.post(
        f"{BASE_ADMIN}/orders/{order.id}/refresh-status", headers=auth_headers
    )
    assert first.status_code == 200, first.text
    fbody = first.json()
    assert fbody["cooldown_cached"] is False
    assert fbody["shipment"]["delivery_status"] == "delivered"
    assert fbody["shipment"]["is_final"] is True
    assert fbody["order_status"] == OrderStatus.DELIVERED.value
    assert len(fbody["tracking_events"]) == 2
    assert calls == 2

    # Second call within 60s hits cooldown and makes ZERO upstream requests
    second = await client.post(
        f"{BASE_ADMIN}/orders/{order.id}/refresh-status", headers=auth_headers
    )
    assert second.status_code == 200, second.text
    assert second.json()["cooldown_cached"] is True
    assert calls == 2


async def test_tracking_pickup_returns_overview_and_locations(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    order = await _make_order(db_session, number="IM-OPS-1")
    shipment = CourierShipment(
        order_id=order.id,
        provider="steadfast",
        invoice=order.number,
        consignment_id="333444",
        tracking_code="SF-OPS-1",
        cod_amount=1300,
        delivery_status="pending",
    )
    db_session.add(shipment)
    await db_session.commit()

    hits: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        hits[path] = hits.get(path, 0) + 1
        if path == "/api/v1/trackings_by_invoice/IM-OPS-1":
            return httpx.Response(200, json={"data": [{"event": "Picked up"}]})
        if path == "/api/v1/create_pickup_request":
            body = json.loads(request.content)
            assert body["address"] == "House 12, Road 4, Mirpur, Dhaka"
            return httpx.Response(200, json={"status": 200, "id": 101})
        if path == "/api/v1/create_return_request":
            body = json.loads(request.content)
            assert body["consignment_id"] == "333444"
            return httpx.Response(200, json={"status": 200, "id": 202})
        if path == "/api/v1/get_return_requests":
            return httpx.Response(200, json={"data": [{"id": 202, "status": "pending"}]})
        if path == "/api/v1/get_return_request/202":
            return httpx.Response(200, json={"id": 202, "status": "pending"})
        if path == "/api/v1/parcel_states":
            return httpx.Response(200, json={"pending": 4, "delivered": 19})
        if path == "/api/v1/get_balance":
            return httpx.Response(200, json={"current_balance": 5400})
        if path == "/api/v1/stats":
            return httpx.Response(200, json={"total_parcels": 23})
        if path == "/api/v1/police_stations":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"district": "Dhaka", "police_station": "Mirpur"},
                        {"district": "Dhaka", "police_station": "Dhanmondi"},
                        {"district": "Chattogram", "police_station": "Pahartali"},
                    ]
                },
            )
        raise AssertionError(f"Unexpected Steadfast path: {path}")

    _install_mock(handler)

    # Tracking (first live, second cached)
    t1 = await client.get(f"{BASE_ADMIN}/orders/{order.id}/tracking", headers=auth_headers)
    assert t1.status_code == 200, t1.text
    assert t1.json()["cached"] is False
    assert t1.json()["tracking_events"] == [{"event": "Picked up"}]

    t2 = await client.get(f"{BASE_ADMIN}/orders/{order.id}/tracking", headers=auth_headers)
    assert t2.status_code == 200
    assert t2.json()["cached"] is True
    assert hits["/api/v1/trackings_by_invoice/IM-OPS-1"] == 1

    # Pickup request using default configured address
    pk = await client.post(f"{BASE_ADMIN}/pickup-request", headers=auth_headers, json={})
    assert pk.status_code == 200, pk.text
    assert pk.json()["ok"] is True

    # Return request create, list, detail + activity logged
    rr = await client.post(
        f"{BASE_ADMIN}/return-requests",
        headers=auth_headers,
        json={"order_id": str(order.id), "reason": "Customer unreachable"},
    )
    assert rr.status_code == 200, rr.text
    rr_list = await client.get(f"{BASE_ADMIN}/return-requests", headers=auth_headers)
    assert rr_list.status_code == 200 and rr_list.json()[0]["id"] == 202
    rr_one = await client.get(f"{BASE_ADMIN}/return-requests/202", headers=auth_headers)
    assert rr_one.status_code == 200 and rr_one.json()["id"] == 202

    ret_act = await db_session.scalar(
        select(OrderActivity).where(
            OrderActivity.order_id == order.id,
            OrderActivity.action == ActivityAction.RETURN_REQUESTED.value,
        )
    )
    assert ret_act is not None

    # Overview (with stats + parcel_states cache)
    ov1 = await client.get(
        f"{BASE_ADMIN}/overview",
        headers=auth_headers,
        params={"start_date": "2026-11-01", "end_date": "2026-11-25"},
    )
    assert ov1.status_code == 200, ov1.text
    assert ov1.json()["balance"] == 5400.0
    assert ov1.json()["parcel_states"]["delivered"] == 19
    assert ov1.json()["stats"]["total_parcels"] == 23
    assert ov1.json()["cached"] is False

    ov2 = await client.get(f"{BASE_ADMIN}/overview", headers=auth_headers)
    assert ov2.status_code == 200 and ov2.json()["cached"] is True
    assert hits["/api/v1/parcel_states"] == 1

    # Sync locations + Public GET /api/v1/delivery/locations
    sync = await client.post(f"{BASE_ADMIN}/sync-locations", headers=auth_headers)
    assert sync.status_code == 200, sync.text
    assert sync.json()["synced_count"] == 3
    assert sync.json()["districts_count"] == 2

    pub = await client.get("/api/v1/delivery/locations")
    assert pub.status_code == 200, pub.text
    loc_data = pub.json()
    assert loc_data["total_areas"] == 3
    assert [d["name"] for d in loc_data["districts"]] == ["Chattogram", "Dhaka"]
    dhaka = next(d for d in loc_data["districts"] if d["name"] == "Dhaka")
    assert dhaka["areas"] == ["Dhanmondi", "Mirpur"]


async def test_courier_rbac_enforcement(
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    viewer_headers = await _login_role(
        db_session, client, email="viewer-courier@implesia.com", role=UserRole.VIEWER
    )
    customer_headers = await _login_role(
        db_session, client, email="cust-courier@implesia.com", role=UserRole.CUSTOMER
    )
    editor_headers = await _login_role(
        db_session, client, email="editor-courier@implesia.com", role=UserRole.EDITOR
    )

    _install_mock(lambda _req: httpx.Response(200, json={"current_balance": 100}))

    # Customer is blocked from all admin courier endpoints, allowed on public delivery locations
    assert (await client.get(f"{BASE_ADMIN}/ping", headers=customer_headers)).status_code == 403
    loc_res = await client.get("/api/v1/delivery/locations", headers=customer_headers)
    assert loc_res.status_code == 200

    # Built-in viewer is blocked on protected orders module reads & writes
    assert (await client.get(f"{BASE_ADMIN}/ping", headers=viewer_headers)).status_code == 403
    assert (
        await client.post(f"{BASE_ADMIN}/sync-locations", headers=viewer_headers)
    ).status_code == 403

    # Editor (orders: read_write) can call admin courier endpoints
    assert (await client.get(f"{BASE_ADMIN}/ping", headers=editor_headers)).status_code == 200
