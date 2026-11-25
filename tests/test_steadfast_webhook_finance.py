"""Tests for Phase 24 — Steadfast webhooks, superadmin COD reconciliation, and live tracking."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.audit_event import AuditAction, AuditEvent
from app.models.courier import CourierShipment, CourierWebhookEvent
from app.models.notification import CustomerNotification
from app.models.order import ActivityAction, Order, OrderActivity, OrderStatus
from app.models.user import User, UserRole
from app.schemas.user import UserCreate
from app.services import telegram_notify, user_service
from app.services.courier.steadfast_client import steadfast_client
from app.services.realtime_hub import STAFF_ORDERS_CHANNEL, realtime_hub, user_channel
from app.services.redis_client import redis_client
from tests.conftest import TEST_PASSWORD

WEBHOOK_URL = "/api/v1/webhooks/steadfast"
BASE_ADMIN = "/api/v1/admin/courier/steadfast"
WEBHOOK_SECRET = "sf-wh-super-secret-2026"


@pytest.fixture(autouse=True)
def _reset_phase24_state(monkeypatch: pytest.MonkeyPatch):
    redis_client.reset_memory_state()
    monkeypatch.setattr(settings, "steadfast_api_key", SecretStr("sf-test-key"))
    monkeypatch.setattr(settings, "steadfast_secret_key", SecretStr("sf-test-secret"))
    monkeypatch.setattr(settings, "steadfast_base_url", "https://portal.packzy.com/api/v1")
    monkeypatch.setattr(settings, "steadfast_webhook_secret", SecretStr(WEBHOOK_SECRET))
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


async def _create_user_and_headers(
    db: AsyncSession,
    client: AsyncClient,
    *,
    email: str,
    role: UserRole,
    phone: str | None = None,
) -> tuple[User, dict[str, str]]:
    user = await user_service.create_user(
        db,
        UserCreate(
            email=email,
            full_name=f"Test {role.value}",
            password=TEST_PASSWORD,
            role=role,
        ),
    )
    if phone:
        user.phone = phone
        await db.commit()
        await db.refresh(user)
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
    return user, {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _make_order_and_shipment(
    db: AsyncSession,
    *,
    number: str,
    consignment_id: str,
    tracking_code: str = "SF-TRK-999",
    status: str = OrderStatus.SHIPPED.value,
    total: int = 2000,
    paid_amount: int = 0,
    due_amount: int | None = 2000,
    user_id: uuid.UUID | None = None,
    phone: str = "01712345678",
    delivery_status: str = "in_review",
    is_final: bool = False,
    tracking_events: list[dict[str, Any]] | None = None,
) -> tuple[Order, CourierShipment]:
    order = Order(
        id=uuid.uuid4(),
        number=number,
        user_id=user_id,
        source="direct",
        customer_name="Hasan Customer",
        phone=phone,
        district="Dhaka",
        area="Mirpur",
        address="House 7, Road 2, Mirpur, Dhaka",
        notes="Internal staff note: check phone",
        delivery_zone="inside",
        subtotal=total - 60,
        shipping=60,
        total=total,
        paid_amount=paid_amount,
        due_amount=due_amount,
        courier_name="Steadfast",
        tracking_number=tracking_code,
        status=status,
    )
    db.add(order)
    await db.flush()
    shipment = CourierShipment(
        order_id=order.id,
        provider="steadfast",
        invoice=number,
        consignment_id=consignment_id,
        tracking_code=tracking_code,
        cod_amount=due_amount if due_amount is not None else total,
        delivery_status=delivery_status,
        is_final=is_final,
        tracking_events=tracking_events or [],
    )
    db.add(shipment)
    await db.commit()
    await db.refresh(order)
    await db.refresh(shipment)
    return order, shipment


# ---------------------------------------------------------------------------
# 1. Webhook Authentication & Idempotency
# ---------------------------------------------------------------------------


async def test_webhook_auth_fail_closed_and_headers(
    db_session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _make_order_and_shipment(db_session, number="IM-A0000001", consignment_id="10001")
    payload = {
        "notification_type": "delivery_status",
        "consignment_id": 10001,
        "invoice": "IM-A0000001",
        "status": "pending",
        "tracking_message": "Parcel at hub",
        "updated_at": "2026-11-25 12:00:00",
    }

    # Missing header -> 401
    r_missing = await client.post(WEBHOOK_URL, json=payload)
    assert r_missing.status_code == 401

    # Wrong bearer token -> 401
    r_wrong = await client.post(
        WEBHOOK_URL,
        json=payload,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r_wrong.status_code == 401

    # Empty secret in production -> fails closed (401)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "steadfast_webhook_secret", SecretStr(""))
    r_prod_empty = await client.post(
        WEBHOOK_URL,
        json=payload,
        headers={"Authorization": f"Bearer {WEBHOOK_SECRET}"},
    )
    assert r_prod_empty.status_code == 401

    # Restore secret: both Bearer token and custom header work
    monkeypatch.setattr(settings, "steadfast_webhook_secret", SecretStr(WEBHOOK_SECRET))
    r_bearer = await client.post(
        WEBHOOK_URL,
        json=payload,
        headers={"Authorization": f"Bearer {WEBHOOK_SECRET}"},
    )
    assert r_bearer.status_code == 200, r_bearer.text
    assert r_bearer.json()["status"] == "processed"

    payload_2 = {
        **payload,
        "tracking_message": "Assigned to rider",
        "updated_at": "2026-11-25 13:00",
    }
    r_custom = await client.post(
        WEBHOOK_URL,
        json=payload_2,
        headers={"X-Steadfast-Webhook-Secret": WEBHOOK_SECRET},
    )
    assert r_custom.status_code == 200, r_custom.text
    assert r_custom.json()["status"] == "processed"


async def test_webhook_idempotency_prevents_double_processing(
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    order, _ = await _make_order_and_shipment(
        db_session, number="IM-A0000002", consignment_id="10002"
    )
    payload = {
        "notification_type": "delivery_status",
        "consignment_id": 10002,
        "invoice": "IM-A0000002",
        "status": "pending",
        "tracking_message": "Arrived at sorting center",
        "updated_at": "2026-11-25 14:00:00",
    }
    headers = {"Authorization": f"Bearer {WEBHOOK_SECRET}"}

    first = await client.post(WEBHOOK_URL, json=payload, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "processed"

    second = await client.post(WEBHOOK_URL, json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["event_key"] == first.json()["event_key"]

    wh_count = await db_session.scalar(select(func.count(CourierWebhookEvent.id)))
    assert wh_count == 1
    act_count = await db_session.scalar(
        select(func.count(OrderActivity.id)).where(
            OrderActivity.order_id == order.id,
            OrderActivity.action == ActivityAction.COURIER_WEBHOOK.value,
        )
    )
    assert act_count == 1


# ---------------------------------------------------------------------------
# 2. Critical Accounting & Status Rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pending_status",
    [
        "delivered_approval_pending",
        "partial_delivered_approval_pending",
        "cancelled_approval_pending",
        "unknown_approval_pending",
    ],
)
async def test_webhook_approval_pending_never_finalizes_order_or_accounting(
    db_session: AsyncSession,
    client: AsyncClient,
    pending_status: str,
) -> None:
    customer, _ = await _create_user_and_headers(
        db_session,
        client,
        email=f"cust-{pending_status}@implesia.com",
        role=UserRole.CUSTOMER,
        phone="01722223333",
    )
    order, shipment = await _make_order_and_shipment(
        db_session,
        number="IM-A0000003",
        consignment_id=f"cid-{pending_status}",
        status=OrderStatus.SHIPPED.value,
        total=1800,
        paid_amount=0,
        due_amount=1800,
        user_id=customer.id,
        phone="01722223333",
    )

    res = await client.post(
        WEBHOOK_URL,
        headers={"Authorization": f"Bearer {WEBHOOK_SECRET}"},
        json={
            "notification_type": "delivery_status",
            "consignment_id": f"cid-{pending_status}",
            "invoice": order.number,
            "status": pending_status,
            "tracking_message": "Rider submitted claim",
        },
    )
    assert res.status_code == 200, res.text
    await db_session.refresh(order)
    await db_session.refresh(shipment)

    # Raw status is recorded, but order/accounting/finalization MUST NOT change
    assert shipment.delivery_status == pending_status
    assert shipment.is_final is False
    assert shipment.is_return_received is False
    assert order.status == OrderStatus.SHIPPED.value
    assert order.delivered_at is None
    assert order.returned_at is None
    assert order.paid_amount == 0
    assert order.due_amount == 1800

    notif_count = await db_session.scalar(
        select(func.count(CustomerNotification.id)).where(CustomerNotification.order_id == order.id)
    )
    assert notif_count == 0


async def test_webhook_confirmed_delivered_transitions_order_and_notifies(
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    customer, _ = await _create_user_and_headers(
        db_session,
        client,
        email="cust-delivered@implesia.com",
        role=UserRole.CUSTOMER,
        phone="01733334444",
    )
    # Order currently 'confirmed' -> webhook 'delivered' steps through to delivered
    order, shipment = await _make_order_and_shipment(
        db_session,
        number="IM-A0000004",
        consignment_id="10004",
        status=OrderStatus.CONFIRMED.value,
        user_id=customer.id,
        phone="01733334444",
    )

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture(channel: str, envelope: dict[str, Any]) -> None:
        published.append((channel, envelope))

    realtime_hub.register_dispatcher(capture)
    try:
        res = await client.post(
            WEBHOOK_URL,
            headers={"Authorization": f"Bearer {WEBHOOK_SECRET}"},
            json={
                "notification_type": "delivery_status",
                "consignment_id": 10004,
                "invoice": "IM-A0000004",
                "status": "delivered",
                "tracking_message": "Delivered to recipient",
            },
        )
    finally:
        realtime_hub.unregister_dispatcher(capture)

    assert res.status_code == 200, res.text
    assert res.json()["order_status"] == OrderStatus.DELIVERED.value

    await db_session.refresh(order)
    await db_session.refresh(shipment)
    assert order.status == OrderStatus.DELIVERED.value
    assert order.delivered_at is not None
    assert shipment.delivery_status == "delivered"
    assert shipment.is_final is True

    # Customer in-app notification + WS push fired
    notif = await db_session.scalar(
        select(CustomerNotification).where(CustomerNotification.order_id == order.id)
    )
    assert notif is not None
    assert notif.user_id == customer.id

    channels_seen = {ch for ch, _ in published}
    assert user_channel(customer.id) in channels_seen
    assert STAFF_ORDERS_CHANNEL in channels_seen


async def test_webhook_partial_delivered_does_not_overwrite_total_and_alerts_staff(
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    order, shipment = await _make_order_and_shipment(
        db_session,
        number="IM-A0000005",
        consignment_id="10005",
        status=OrderStatus.SHIPPED.value,
        total=3000,
        paid_amount=0,
        due_amount=3000,
    )

    res = await client.post(
        WEBHOOK_URL,
        headers={"Authorization": f"Bearer {WEBHOOK_SECRET}"},
        json={
            "notification_type": "delivery_status",
            "consignment_id": 10005,
            "invoice": "IM-A0000005",
            "status": "partial_delivered",
            "cod_amount": 1500,
            "tracking_message": "Customer kept 1 of 2 items",
        },
    )
    assert res.status_code == 200, res.text
    await db_session.refresh(order)
    await db_session.refresh(shipment)

    assert shipment.delivery_status == "partial_delivered"
    assert shipment.is_final is True
    # Total, paid, and order status untouched so staff can review cleanly
    assert order.total == 3000
    assert order.paid_amount == 0
    assert order.due_amount == 3000
    assert order.status == OrderStatus.SHIPPED.value

    act = await db_session.scalar(
        select(OrderActivity).where(
            OrderActivity.order_id == order.id,
            OrderActivity.action == ActivityAction.COURIER_WEBHOOK.value,
        )
    )
    assert act is not None
    assert (act.detail or {}).get("priority") == "high"


async def test_webhook_cancelled_return_progression_and_return_received_flag(
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    order, shipment = await _make_order_and_shipment(
        db_session,
        number="IM-A0000006",
        consignment_id="10006",
        status=OrderStatus.SHIPPED.value,
    )
    headers = {"Authorization": f"Bearer {WEBHOOK_SECRET}"}

    # Step 1: cancelled -> is_return_received stays False
    r1 = await client.post(
        WEBHOOK_URL,
        headers=headers,
        json={"consignment_id": 10006, "invoice": "IM-A0000006", "status": "cancelled"},
    )
    assert r1.status_code == 200
    await db_session.refresh(shipment)
    await db_session.refresh(order)
    assert shipment.delivery_status == "cancelled"
    assert shipment.is_return_received is False
    assert order.status == OrderStatus.SHIPPED.value

    # Step 2: cancelled_return_proccessing -> still False
    r2 = await client.post(
        WEBHOOK_URL,
        headers=headers,
        json={
            "consignment_id": 10006,
            "invoice": "IM-A0000006",
            "status": "cancelled_return_proccessing",
        },
    )
    assert r2.status_code == 200
    await db_session.refresh(shipment)
    assert shipment.return_status == "cancelled_return_proccessing"
    assert shipment.is_return_received is False

    # Step 3: cancelled_return_rider_assigned -> still False
    r3 = await client.post(
        WEBHOOK_URL,
        headers=headers,
        json={
            "consignment_id": 10006,
            "invoice": "IM-A0000006",
            "status": "cancelled_return_rider_assigned",
        },
    )
    assert r3.status_code == 200
    await db_session.refresh(shipment)
    assert shipment.return_status == "cancelled_return_rider_assigned"
    assert shipment.is_return_received is False

    # Step 4: cancelled_return_received -> ONLY NOW is_return_received becomes True!
    r4 = await client.post(
        WEBHOOK_URL,
        headers=headers,
        json={
            "consignment_id": 10006,
            "invoice": "IM-A0000006",
            "status": "cancelled_return_received",
        },
    )
    assert r4.status_code == 200
    assert r4.json()["is_return_received"] is True
    await db_session.refresh(shipment)
    assert shipment.return_status == "cancelled_return_received"
    assert shipment.is_return_received is True


async def test_webhook_hold_and_exceptional_trigger_telegram_alert(
    db_session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order, _ = await _make_order_and_shipment(
        db_session, number="IM-A0000007", consignment_id="10007"
    )
    sent: list[dict[str, Any]] = []

    def fake_schedule(background: Any, **kwargs: Any) -> None:
        sent.append(kwargs)

    monkeypatch.setattr(telegram_notify, "schedule_courier_alert", fake_schedule)

    for st in ("hold", "exceptional"):
        res = await client.post(
            WEBHOOK_URL,
            headers={"Authorization": f"Bearer {WEBHOOK_SECRET}"},
            json={
                "consignment_id": 10007,
                "invoice": order.number,
                "status": st,
                "tracking_message": f"Parcel marked {st}",
            },
        )
        assert res.status_code == 200

    assert [item["status"] for item in sent] == ["hold", "exceptional"]
    assert all(item["order_number"] == order.number for item in sent)


# ---------------------------------------------------------------------------
# 3. Superadmin-Only Finance RBAC & Idempotent COD Reconciliation
# ---------------------------------------------------------------------------


async def test_finance_endpoints_strictly_superadmin_only(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    _, editor_headers = await _create_user_and_headers(
        db_session, client, email="ed-fin@implesia.com", role=UserRole.EDITOR
    )
    _, viewer_headers = await _create_user_and_headers(
        db_session, client, email="vw-fin@implesia.com", role=UserRole.VIEWER
    )
    _, cust_headers = await _create_user_and_headers(
        db_session, client, email="cu-fin@implesia.com", role=UserRole.CUSTOMER
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/get_balance":
            return httpx.Response(200, json={"current_balance": 45200})
        if request.url.path == "/api/v1/payments":
            return httpx.Response(200, json={"data": [{"id": "PAY-1", "amount": 45200}]})
        if request.url.path == "/api/v1/payments/PAY-1":
            return httpx.Response(200, json={"id": "PAY-1", "consignments": []})
        raise AssertionError(request.url.path)

    _install_mock(handler)

    for bad_headers in (editor_headers, viewer_headers, cust_headers):
        assert (await client.get(f"{BASE_ADMIN}/balance", headers=bad_headers)).status_code == 403
        assert (await client.get(f"{BASE_ADMIN}/payments", headers=bad_headers)).status_code == 403
        assert (
            await client.get(f"{BASE_ADMIN}/payments/PAY-1", headers=bad_headers)
        ).status_code == 403
        assert (
            await client.post(f"{BASE_ADMIN}/payments/PAY-1/reconcile", headers=bad_headers)
        ).status_code == 403

    # Superadmin succeeds on all 4 endpoints
    bal = await client.get(f"{BASE_ADMIN}/balance", headers=auth_headers)
    assert bal.status_code == 200 and bal.json()["current_balance"] == 45200.0
    pays = await client.get(f"{BASE_ADMIN}/payments", headers=auth_headers)
    assert pays.status_code == 200 and pays.json()["total"] == 1
    det = await client.get(f"{BASE_ADMIN}/payments/PAY-1", headers=auth_headers)
    assert det.status_code == 200
    rec = await client.post(f"{BASE_ADMIN}/payments/PAY-1/reconcile", headers=auth_headers)
    assert rec.status_code == 200


async def test_cod_reconciliation_cross_matches_and_is_idempotent(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    o1, s1 = await _make_order_and_shipment(
        db_session,
        number="IM-B0000001",
        consignment_id="20001",
        status=OrderStatus.DELIVERED.value,
        total=1500,
        paid_amount=0,
        due_amount=1500,
    )
    o2, s2 = await _make_order_and_shipment(
        db_session,
        number="IM-B0000002",
        consignment_id="20002",
        status=OrderStatus.DELIVERED.value,
        total=2000,
        paid_amount=500,  # Advance paid via Bangla QR
        due_amount=1500,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/payments":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "PAY-901", "amount": 3000},
                        {"id": "PAY-902", "amount": 1200},
                        {"id": "PAY-903", "amount": 900},
                    ]
                },
            )
        if request.url.path == "/api/v1/payments/PAY-901":
            return httpx.Response(
                200,
                json={
                    "id": "PAY-901",
                    "status": "paid",
                    "amount": 3000,
                    "consignments": [
                        {"consignment_id": "20001", "invoice": "IM-B0000001", "cod_amount": 1500},
                        {"consignment_id": "20002", "invoice": "IM-B0000002", "cod_amount": 1500},
                        {"consignment_id": "99999", "invoice": "UNKNOWN-INV", "cod_amount": 750},
                    ],
                },
            )
        raise AssertionError(request.url.path)

    _install_mock(handler)

    # Paginated payments list
    page1 = await client.get(
        f"{BASE_ADMIN}/payments",
        headers=auth_headers,
        params={"page": 1, "page_size": 2},
    )
    assert page1.status_code == 200
    assert page1.json()["total"] == 3
    assert page1.json()["pages"] == 2
    assert len(page1.json()["items"]) == 2

    # Payment detail cross-match preview
    detail = await client.get(f"{BASE_ADMIN}/payments/PAY-901", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    dbody = detail.json()
    assert dbody["pending_reconcile_count"] == 2
    assert dbody["already_reconciled_count"] == 0
    assert len(dbody["matched_orders"]) == 2
    assert len(dbody["unmatched_parcels"]) == 1

    # First reconcile run
    rec1 = await client.post(f"{BASE_ADMIN}/payments/PAY-901/reconcile", headers=auth_headers)
    assert rec1.status_code == 200, rec1.text
    r1 = rec1.json()
    assert r1["reconciled_count"] == 2
    assert r1["already_reconciled_count"] == 0
    assert r1["unmatched_count"] == 1
    assert r1["total_amount_applied"] == 3000

    await db_session.refresh(o1)
    await db_session.refresh(o2)
    await db_session.refresh(s1)
    await db_session.refresh(s2)

    assert o1.paid_amount == 1500 and o1.due_amount == 0
    assert o2.paid_amount == 2000 and o2.due_amount == 0
    assert s1.settled_payment_id == "PAY-901" and s1.settled_amount == 1500 and s1.settled_at
    assert s2.settled_payment_id == "PAY-901" and s2.settled_amount == 1500 and s2.settled_at

    # Audit event + payment_updated activities written
    audit_rows = (
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.action == AuditAction.COURIER_COD_RECONCILED.value)
        )
    ).all()
    assert len(audit_rows) == 1

    pay_acts = (
        await db_session.scalars(
            select(OrderActivity).where(
                OrderActivity.action == ActivityAction.PAYMENT_UPDATED.value
            )
        )
    ).all()
    assert len(pay_acts) == 2

    # Second reconcile click -> 100% idempotent, ZERO double counting
    rec2 = await client.post(f"{BASE_ADMIN}/payments/PAY-901/reconcile", headers=auth_headers)
    assert rec2.status_code == 200, rec2.text
    r2 = rec2.json()
    assert r2["reconciled_count"] == 0
    assert r2["already_reconciled_count"] == 2
    assert r2["total_amount_applied"] == 0

    await db_session.refresh(o1)
    await db_session.refresh(o2)
    assert o1.paid_amount == 1500 and o1.due_amount == 0
    assert o2.paid_amount == 2000 and o2.due_amount == 0

    # No duplicate audit or activity rows created
    audit_count_after = await db_session.scalar(
        select(func.count(AuditEvent.id)).where(
            AuditEvent.action == AuditAction.COURIER_COD_RECONCILED.value
        )
    )
    assert audit_count_after == 1


# ---------------------------------------------------------------------------
# 4. Customer & Public Live Tracking Sanitization
# ---------------------------------------------------------------------------


async def test_customer_and_public_tracking_sanitizes_internal_fields(
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    customer, cust_headers = await _create_user_and_headers(
        db_session,
        client,
        email="cust-track@implesia.com",
        role=UserRole.CUSTOMER,
        phone="01744445555",
    )
    order, _ = await _make_order_and_shipment(
        db_session,
        number="IM-C0000001",
        consignment_id="30001",
        tracking_code="SF-LIVE-30001",
        status=OrderStatus.SHIPPED.value,
        user_id=customer.id,
        phone="01744445555",
        delivery_status="delivered_approval_pending",
        is_final=False,
    )

    api_hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_hits
        api_hits += 1
        assert request.url.path == "/api/v1/trackings_by_invoice/IM-C0000001"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "status": "in_review",
                        "tracking_message": "Received at Mirpur hub",
                        "created_at": "2026-11-25T08:00:00Z",
                        "fraud_score": 0.12,
                        "internal_note": "SECRET_STAFF_NOTE",
                    },
                    {
                        "status": "delivered_approval_pending",
                        "tracking_message": "Rider marked delivered_approval_pending",
                        "created_at": "2026-11-25T11:00:00Z",
                        "merchant_reports": [{"reason": "secret"}],
                    },
                ]
            },
        )

    _install_mock(handler)

    # 1. Customer dashboard tracking endpoint fetches live (and caches 60s)
    cust_res = await client.get(
        f"/api/v1/customer/orders/{order.number}/tracking",
        headers=cust_headers,
    )
    assert cust_res.status_code == 200, cust_res.text
    cbody = cust_res.json()
    assert cbody["tracking_url"] == "https://steadfast.com.bd/t/SF-LIVE-30001"
    assert len(cbody["live_events"]) == 2
    assert api_hits == 1

    # Verify strict sanitization — NO raw approval_pending, fraud_score, or internal notes
    serialized_cust = str(cbody["live_events"]).lower()
    assert "approval_pending" not in serialized_cust
    assert "fraud_score" not in serialized_cust
    assert "secret_staff_note" not in serialized_cust
    assert "merchant_reports" not in serialized_cust
    assert cbody["live_events"][1]["status"] == "in_transit"
    assert cbody["live_events"][1]["label"] == "Delivery Update in Progress"

    # 2. Public order lookup enriches live_events & uses 60s cache (no 2nd Steadfast hit)
    pub_res = await client.post(
        "/api/v1/orders/lookup",
        json={"number": order.number, "phone": "01744445555"},
    )
    assert pub_res.status_code == 200, pub_res.text
    pbody = pub_res.json()
    assert pbody["tracking_url"] == "https://steadfast.com.bd/t/SF-LIVE-30001"
    assert len(pbody["live_events"]) == 2
    assert api_hits == 1  # Served from 60s Redis cache

    serialized_pub = str(pbody["live_events"]).lower()
    assert "approval_pending" not in serialized_pub
    assert "fraud_score" not in serialized_pub
    assert "secret_staff_note" not in serialized_pub
