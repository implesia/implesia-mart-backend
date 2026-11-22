"""Comprehensive tests for Phase 19 — High-Scale, Seller-Ready Direct Communication Engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication import (
    Conversation,
    ConversationStatus,
    ConversationType,
    Message,
)
from app.models.notification import CustomerNotification
from app.models.order import Order, OrderStatus
from app.models.product import Product, StockStatus
from app.models.user import User, UserRole
from app.schemas.customer import CustomerRegisterRequest
from app.schemas.user import RoleCreate, UserCreate
from app.services import (
    communication_service,
    customer_auth_service,
    permission_service,
    user_service,
)
from app.services.realtime_hub import (
    STAFF_COMMUNICATION_CHANNEL,
    conversation_channel,
    realtime_hub,
    user_channel,
)
from app.services.redis_client import redis_client
from app.services.ws_manager import WSConnection, ws_manager
from tests.conftest import TEST_PASSWORD

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(autouse=True)
def _reset_realtime() -> Any:
    redis_client.reset_memory_state()
    ws_manager.reset()
    yield
    redis_client.reset_memory_state()
    ws_manager.reset()


async def _register_customer(
    db: AsyncSession,
    client: AsyncClient,
    *,
    name: str,
    phone: str,
    email: str,
) -> tuple[User, dict[str, str]]:
    user = await customer_auth_service.register_customer(
        db,
        CustomerRegisterRequest(
            full_name=name,
            phone=phone,
            email=email,
            password="ShopperPassword123!",
        ),
    )
    login = await client.post(
        "/api/v1/customer/auth/login",
        json={"identifier": phone, "password": "ShopperPassword123!"},
    )
    assert login.status_code == 200, login.text
    return user, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _login_staff(
    db: AsyncSession,
    client: AsyncClient,
    *,
    email: str,
    full_name: str,
    role: str,
) -> tuple[User, dict[str, str]]:
    user = await user_service.create_user(
        db,
        UserCreate(
            email=email,
            full_name=full_name,
            password=TEST_PASSWORD,
            role=role,
        ),
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return user, {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_communication_rbac_matrix_and_custom_role_isolation(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # Module is registered with expected defaults
    matrix = await client.get("/api/v1/users/roles-matrix", headers=auth_headers)
    assert matrix.status_code == 200, matrix.text
    body = matrix.json()
    module_keys = {m["key"] for m in body["module_definitions"]}
    assert "communication" in module_keys

    perms_by_role = {
        r["role"]: {p["module_key"]: p["access"] for p in r["permissions"]}
        for r in body["roles"]
    }
    assert perms_by_role["superadmin"]["communication"] == "full"
    assert perms_by_role["editor"]["communication"] == "read_write"
    assert perms_by_role["viewer"]["communication"] == "read_only"
    assert perms_by_role["customer"]["communication"] == "none"

    # Viewer can read summary/list, but gets 403 on write endpoints
    _, viewer_headers = await _login_staff(
        db_session,
        client,
        email="comm-viewer@implesia.com",
        full_name="Comm Viewer",
        role=UserRole.VIEWER.value,
    )
    assert (
        await client.get("/api/v1/admin/communication/summary", headers=viewer_headers)
    ).status_code == 200

    # Create a customer conversation so we have a real conversation id
    _, cust_headers = await _register_customer(
        db_session,
        client,
        name="Ayesha",
        phone="01722001122",
        email="ayesha@example.com",
    )
    created = await client.post(
        "/api/v1/customer/conversations",
        headers=cust_headers,
        json={"subject": "Sizing help", "initial_message": "Is M in stock?"},
    )
    assert created.status_code == 201, created.text
    conv_id = created.json()["id"]

    # Viewer cannot post messages or patch conversation
    assert (
        await client.post(
            f"/api/v1/admin/communication/conversations/{conv_id}/messages",
            headers=viewer_headers,
            json={"body": "Viewer reply"},
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/admin/communication/conversations/{conv_id}",
            headers=viewer_headers,
            json={"status": "pending"},
        )
    ).status_code == 403

    # Customer gets 403 on all admin communication routes
    assert (
        await client.get("/api/v1/admin/communication/summary", headers=cust_headers)
    ).status_code == 403

    # Custom staff role without communication permission gets 403, then succeeds once granted
    admin = await user_service.get_by_email(db_session, "admin@implesia.com")
    assert admin is not None
    await permission_service.create_role(
        db_session,
        RoleCreate(label="Support Agent", slug="support_agent"),
        actor=admin,
    )
    _, agent_headers = await _login_staff(
        db_session,
        client,
        email="agent@implesia.com",
        full_name="Support Agent One",
        role="support_agent",
    )
    assert (
        await client.get("/api/v1/admin/communication/conversations", headers=agent_headers)
    ).status_code == 403

    grant_res = await client.put(
        "/api/v1/users/roles-matrix",
        headers=auth_headers,
        json={
            "updates": [
                {
                    "role": "support_agent",
                    "module_key": "communication",
                    "access_level": "read_write",
                }
            ]
        },
    )
    assert grant_res.status_code == 200, grant_res.text
    assert (
        await client.get("/api/v1/admin/communication/conversations", headers=agent_headers)
    ).status_code == 200
    reply = await client.post(
        f"/api/v1/admin/communication/conversations/{conv_id}/messages",
        headers=agent_headers,
        json={"body": "Yes, size M is ready to ship!"},
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["sender_role"] == "support_agent"


@pytest.mark.asyncio
async def test_customer_isolation_reuse_and_internal_note_privacy(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    cust_a, headers_a = await _register_customer(
        db_session,
        client,
        name="Customer A",
        phone="01733001122",
        email="custa@example.com",
    )
    cust_a_id = cust_a.id
    cust_b, headers_b = await _register_customer(
        db_session,
        client,
        name="Customer B",
        phone="01733001133",
        email="custb@example.com",
    )
    cust_b_id = cust_b.id

    # Start conversation and verify reuse for same customer/context
    c1 = await client.post(
        "/api/v1/customer/conversations",
        headers=headers_a,
        json={"subject": "Delivery question", "initial_message": "When does it arrive?"},
    )
    assert c1.status_code == 201, c1.text
    conv_id = c1.json()["id"]

    c2 = await client.post(
        "/api/v1/customer/conversations",
        headers=headers_a,
        json={"subject": "Another subject"},
    )
    assert c2.status_code == 201
    assert c2.json()["id"] == conv_id  # Reused open support conversation

    # Customer B cannot read, post, mark read, or upload to Customer A's thread
    assert (
        await client.get(
            f"/api/v1/customer/conversations/{conv_id}/messages", headers=headers_b
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/customer/conversations/{conv_id}/messages",
            headers=headers_b,
            json={"body": "Sneaky message"},
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/customer/conversations/{conv_id}/read", headers=headers_b
        )
    ).status_code == 404
    b_list = await client.get("/api/v1/customer/conversations", headers=headers_b)
    assert b_list.status_code == 200
    assert b_list.json()["items"] == []

    # Capture WS events to verify internal notes NEVER go to customer channel
    events: list[tuple[str, dict[str, Any]]] = []

    async def _capture(ch: str, env: dict[str, Any]) -> None:
        events.append((ch, env))

    realtime_hub.register_dispatcher(_capture)
    try:
        # Staff posts an internal note
        note_res = await client.post(
            f"/api/v1/admin/communication/conversations/{conv_id}/messages",
            headers=auth_headers,
            json={"body": "VIP customer — check courier priority", "is_internal_note": True},
        )
        assert note_res.status_code == 201, note_res.text
        assert note_res.json()["is_internal_note"] is True

        # Internal note published to staff & conv channels, NEVER to rt:user:{customer_id}
        channels_for_note = {ch for ch, env in events if env["type"] == "message.created"}
        assert STAFF_COMMUNICATION_CHANNEL in channels_for_note
        assert conversation_channel(conv_id) in channels_for_note
        assert user_channel(cust_a_id) not in channels_for_note

        # WSConnectionManager also blocks internal note frames on customer sockets
        delivered_to_customer: list[dict[str, Any]] = []
        delivered_to_admin: list[dict[str, Any]] = []

        class _FakeWS:
            def __init__(self, sink: list[dict[str, Any]]) -> None:
                self.sink = sink

            async def send_json(self, data: dict[str, Any]) -> None:
                self.sink.append(data)

        cust_conn = WSConnection(
            websocket=_FakeWS(delivered_to_customer),  # type: ignore[arg-type]
            user_id=str(cust_a_id),
            role="customer",
            scope="customer",
        )
        admin_conn = WSConnection(
            websocket=_FakeWS(delivered_to_admin),  # type: ignore[arg-type]
            user_id=str(uuid.uuid4()),
            role="superadmin",
            scope="admin",
        )
        ws_manager.subscribe(cust_conn, conversation_channel(conv_id))
        ws_manager.subscribe(admin_conn, conversation_channel(conv_id))
        await ws_manager.dispatch_channel(
            conversation_channel(conv_id),
            {"type": "message.created", "data": {"body": "secret", "is_internal_note": True}},
        )
        assert delivered_to_customer == []
        assert len(delivered_to_admin) == 1

        # Customer sees ZERO internal notes, preview is untouched, and unread count stays 0
        cust_msgs = await client.get(
            f"/api/v1/customer/conversations/{conv_id}/messages", headers=headers_a
        )
        assert cust_msgs.status_code == 200
        assert len(cust_msgs.json()["items"]) == 1
        assert all(not m["is_internal_note"] for m in cust_msgs.json()["items"])

        cust_list = await client.get("/api/v1/customer/conversations", headers=headers_a)
        assert cust_list.status_code == 200
        assert cust_list.json()["items"][0]["last_message_preview"] == "When does it arrive?"
        assert cust_list.json()["items"][0]["unread_count"] == 0
        assert cust_list.json()["total_unread"] == 0

        # Admin DOES see the internal note
        admin_msgs = await client.get(
            f"/api/v1/admin/communication/conversations/{conv_id}/messages",
            headers=auth_headers,
        )
        assert admin_msgs.status_code == 200
        assert len(admin_msgs.json()["items"]) == 2
        assert any(m["is_internal_note"] for m in admin_msgs.json()["items"])

        # Now staff sends a public reply -> customer sees it, unread=1, WS fires to user channel
        events.clear()
        pub_res = await client.post(
            f"/api/v1/admin/communication/conversations/{conv_id}/messages",
            headers=auth_headers,
            json={"body": "Your parcel arrives tomorrow!", "is_internal_note": False},
        )
        assert pub_res.status_code == 201
        pub_channels = {ch for ch, env in events if env["type"] == "message.created"}
        assert user_channel(cust_a_id) in pub_channels
        assert STAFF_COMMUNICATION_CHANNEL in pub_channels
        assert conversation_channel(conv_id) in pub_channels

        cust_list_after = await client.get("/api/v1/customer/conversations", headers=headers_a)
        assert cust_list_after.json()["items"][0]["unread_count"] == 1
        assert cust_list_after.json()["total_unread"] == 1

        # Customer marks conversation read -> unread returns to 0
        mark = await client.post(
            f"/api/v1/customer/conversations/{conv_id}/read", headers=headers_a
        )
        assert mark.status_code == 200
        assert mark.json()["unread_count"] == 0
        cust_list_read = await client.get("/api/v1/customer/conversations", headers=headers_a)
        assert cust_list_read.json()["total_unread"] == 0

        # Verify can_access_conversation ownership check
        assert (
            await communication_service.can_access_conversation(
                db_session, cust_a_id, "customer", "customer", uuid.UUID(conv_id)
            )
            is True
        )
        assert (
            await communication_service.can_access_conversation(
                db_session, cust_b_id, "customer", "customer", uuid.UUID(conv_id)
            )
            is False
        )
    finally:
        realtime_hub.unregister_dispatcher(_capture)


@pytest.mark.asyncio
async def test_cursor_pagination_deterministic_zero_duplicates(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    cust, cust_headers = await _register_customer(
        db_session,
        client,
        name="Paginator",
        phone="01744001122",
        email="page@example.com",
    )
    created = await client.post(
        "/api/v1/customer/conversations",
        headers=cust_headers,
        json={"subject": "Long thread"},
    )
    conv_id = uuid.UUID(created.json()["id"])

    # Insert 7 messages (including two sharing an identical timestamp to test tie-breaking by id)
    base = datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC)
    timestamps = [
        base + timedelta(seconds=1),
        base + timedelta(seconds=2),
        base + timedelta(seconds=3),
        base + timedelta(seconds=3),  # deliberate tie!
        base + timedelta(seconds=4),
        base + timedelta(seconds=5),
        base + timedelta(seconds=6),
    ]
    inserted_ids: set[str] = set()
    for idx, ts in enumerate(timestamps):
        m = Message(
            conversation_id=conv_id,
            sender_id=cust.id,
            sender_role="customer",
            body=f"msg-{idx}",
            is_internal_note=False,
            created_at=ts,
        )
        db_session.add(m)
        await db_session.flush()
        inserted_ids.add(str(m.id))
    await db_session.commit()

    # Walk with limit=3 -> expect 3, 3, 1 (total 7 unique ids, zero overlap)
    seen: list[str] = []
    before_created_at: str | None = None
    before_id: str | None = None
    page_sizes: list[int] = []

    for _ in range(5):
        params: dict[str, Any] = {"limit": 3}
        if before_created_at and before_id:
            params["before_created_at"] = before_created_at
            params["before_id"] = before_id
        res = await client.get(
            f"/api/v1/customer/conversations/{conv_id}/messages",
            headers=cust_headers,
            params=params,
        )
        assert res.status_code == 200, res.text
        data = res.json()
        page_sizes.append(len(data["items"]))
        seen.extend(item["id"] for item in data["items"])
        if not data["has_more"]:
            break
        before_created_at = data["next_before_created_at"]
        before_id = data["next_before_id"]

    assert page_sizes == [3, 3, 1]
    assert len(seen) == 7
    assert set(seen) == inserted_ids


@pytest.mark.asyncio
async def test_admin_summary_filters_context_pane_assignment_and_seller_types(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    cust, cust_headers = await _register_customer(
        db_session,
        client,
        name="Farhana Rahman",
        phone="01855001122",
        email="farhana@example.com",
    )
    cust_id = cust.id
    cust_full_name = cust.full_name
    cust_phone = cust.phone or "01855001122"
    cust_email = cust.email
    seller, _ = await _register_customer(
        db_session,
        client,
        name="Jamdanee Atelier",
        phone="01855009999",
        email="seller@example.com",
    )
    seller_id = seller.id
    editor, _ = await _login_staff(
        db_session,
        client,
        email="comm-editor@implesia.com",
        full_name="Comm Editor",
        role=UserRole.EDITOR.value,
    )
    editor_id = editor.id

    product = Product(
        title="Handloom Tangail Saree",
        slug="handloom-tangail-saree",
        price=3200,
        quantity=4,
        status=StockStatus.AVAILABLE.value,
        published=True,
        content={},
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    product_id = product.id

    order = Order(
        number="IMP-COMM-1001",
        user_id=cust_id,
        status=OrderStatus.CONFIRMED.value,
        source="direct",
        origin="online",
        customer_name=cust_full_name,
        phone=cust_phone,
        email=cust_email,
        district="Dhaka",
        area="Banani",
        address="Road 11, Banani",
        delivery_zone="inside_dhaka",
        payment_method="cod",
        subtotal=3200,
        shipping=60,
        total=3260,
        paid_amount=0,
        due_amount=3260,
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    order_id = order.id

    # 1. Customer support thread linked to order + product
    c_res = await client.post(
        "/api/v1/customer/conversations",
        headers=cust_headers,
        json={
            "order_id": str(order_id),
            "product_id": str(product_id),
            "subject": "Order color check",
            "initial_message": "Can I confirm the border color?",
        },
    )
    assert c_res.status_code == 201, c_res.text
    cs_conv_id = c_res.json()["id"]

    # 2. Seller-ready threads (seller_support + customer_seller)
    now = datetime.now(UTC)
    seller_support = Conversation(
        type=ConversationType.SELLER_SUPPORT.value,
        seller_id=seller_id,
        subject="Payout schedule",
        status=ConversationStatus.PENDING.value,
        last_message_at=now,
        last_message_preview="When is settlement?",
    )
    cust_seller = Conversation(
        type=ConversationType.CUSTOMER_SELLER.value,
        customer_id=cust_id,
        seller_id=seller_id,
        product_id=product_id,
        subject="Blouse piece length",
        status=ConversationStatus.OPEN.value,
        last_message_at=now,
        last_message_preview="Does it include blouse piece?",
    )
    db_session.add_all([seller_support, cust_seller])
    await db_session.flush()
    db_session.add(
        Message(
            conversation_id=seller_support.id,
            sender_id=seller_id,
            sender_role="seller",
            body="When is settlement?",
            is_internal_note=False,
            created_at=now,
        )
    )
    await db_session.commit()

    # Summary reports across all 3 channel types
    summary = await client.get("/api/v1/admin/communication/summary", headers=auth_headers)
    assert summary.status_code == 200, summary.text
    s = summary.json()
    assert s["open_count"] == 2
    assert s["pending_count"] == 1
    assert s["unassigned_count"] == 3
    assert s["unread_conversations_count"] == 2
    by_type = {b["type"]: b for b in s["by_type"]}
    assert by_type["customer_support"]["open"] == 1
    assert by_type["seller_support"]["pending"] == 1
    assert by_type["customer_seller"]["open"] == 1

    # Filter by type, status, q (customer name & phone), and assigned
    only_seller = await client.get(
        "/api/v1/admin/communication/conversations",
        headers=auth_headers,
        params={"type": "seller_support"},
    )
    assert only_seller.status_code == 200
    assert only_seller.json()["total"] == 1

    by_phone = await client.get(
        "/api/v1/admin/communication/conversations",
        headers=auth_headers,
        params={"q": "01855001122"},
    )
    assert by_phone.status_code == 200
    assert by_phone.json()["total"] == 2

    # Assign editor + move to pending, verify detail context pane
    patched = await client.patch(
        f"/api/v1/admin/communication/conversations/{cs_conv_id}",
        headers=auth_headers,
        json={"status": "pending", "assigned_staff_id": str(editor_id)},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "pending"
    assert patched.json()["assigned_staff"]["id"] == str(editor_id)

    # Mark read by admin clears unread count for admin
    await client.post(
        f"/api/v1/admin/communication/conversations/{cs_conv_id}/read",
        headers=auth_headers,
    )

    detail = await client.get(
        f"/api/v1/admin/communication/conversations/{cs_conv_id}",
        headers=auth_headers,
    )
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["customer"]["full_name"] == "Farhana Rahman"
    assert d["order"]["number"] == "IMP-COMM-1001"
    assert d["product"]["slug"] == "handloom-tangail-saree"
    assert len(d["recent_orders"]) == 1
    assert d["unread_count"] == 0

    # Unassign explicitly via null
    unassigned = await client.patch(
        f"/api/v1/admin/communication/conversations/{cs_conv_id}",
        headers=auth_headers,
        json={"assigned_staff_id": None},
    )
    assert unassigned.status_code == 200
    assert unassigned.json()["assigned_staff_id"] is None


@pytest.mark.asyncio
async def test_attachments_rate_limit_and_offline_notification_throttle(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    cust, cust_headers = await _register_customer(
        db_session,
        client,
        name="Offline Buyer",
        phone="01966001122",
        email="offline@example.com",
    )
    cust_id = cust.id
    created = await client.post(
        "/api/v1/customer/conversations",
        headers=cust_headers,
        json={"subject": "Photo attached"},
    )
    conv_id = created.json()["id"]

    # Valid PNG upload succeeds under /media/chat/
    up = await client.post(
        f"/api/v1/customer/conversations/{conv_id}/attachment",
        headers=cust_headers,
        files={"file": ("photo.png", _TINY_PNG, "image/png")},
    )
    assert up.status_code == 201, up.text
    url = up.json()["url"]
    assert url.startswith("/media/chat/")

    # Invalid file rejected with 422
    bad_up = await client.post(
        f"/api/v1/customer/conversations/{conv_id}/attachment",
        headers=cust_headers,
        files={"file": ("evil.svg", b"<svg></svg>", "image/svg+xml")},
    )
    assert bad_up.status_code == 422

    # Send message with attachment
    msg_att = await client.post(
        f"/api/v1/customer/conversations/{conv_id}/messages",
        headers=cust_headers,
        json={"body": "See photo", "attachment_url": url},
    )
    assert msg_att.status_code == 201
    assert msg_att.json()["attachment_url"] == url

    # Empty body without attachment -> 422
    assert (
        await client.post(
            f"/api/v1/customer/conversations/{conv_id}/messages",
            headers=cust_headers,
            json={"body": "   "},
        )
    ).status_code == 422

    # Customer is OFFLINE -> first admin reply inserts 1 CustomerNotification, 2nd is throttled!
    assert await redis_client.is_user_online(str(cust_id)) is False
    r1 = await client.post(
        f"/api/v1/admin/communication/conversations/{conv_id}/messages",
        headers=auth_headers,
        json={"body": "First support reply"},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        f"/api/v1/admin/communication/conversations/{conv_id}/messages",
        headers=auth_headers,
        json={"body": "Second rapid reply"},
    )
    assert r2.status_code == 201

    notifs = list(
        (
            await db_session.scalars(
                select(CustomerNotification).where(CustomerNotification.user_id == cust_id)
            )
        ).all()
    )
    assert len(notifs) == 1
    assert notifs[0].type == "support_message"

    # Rate limit: 20 messages / 10 seconds -> 21st returns 429
    redis_client.reset_memory_state()
    for i in range(20):
        ok = await client.post(
            f"/api/v1/customer/conversations/{conv_id}/messages",
            headers=cust_headers,
            json={"body": f"burst-{i}"},
        )
        assert ok.status_code == 201, ok.text

    blocked = await client.post(
        f"/api/v1/customer/conversations/{conv_id}/messages",
        headers=cust_headers,
        json={"body": "burst-21"},
    )
    assert blocked.status_code == 429
