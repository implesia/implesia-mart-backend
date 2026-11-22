import asyncio
import inspect
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.v1.endpoints.ws import websocket_endpoint
from app.core.config import Settings
from app.main import app
from app.models.order import Order, OrderStatus
from app.models.product import Product, StockStatus
from app.models.user import User
from app.schemas.customer import CustomerRegisterRequest
from app.schemas.user import RoleCreate, RolePermissionUpdateItem, UserCreate
from app.services import (
    customer_auth_service,
    notification_service,
    permission_service,
    user_service,
)
from app.services.realtime_hub import (
    STAFF_COMMUNICATION_CHANNEL,
    STAFF_ORDERS_CHANNEL,
    conversation_channel,
    realtime_hub,
    user_channel,
)
from app.services.redis_client import redis_client
from app.services.ws_manager import (
    WS_CLOSE_AUTH_FAILED,
    WS_CLOSE_IDLE_TIMEOUT,
    WS_CLOSE_MESSAGE_TOO_BIG,
    WS_CLOSE_TOO_MANY_CONNECTIONS,
    ws_manager,
)
from tests.conftest import TEST_PASSWORD


@pytest.fixture(autouse=True)
def _clean_realtime_state() -> Any:
    ws_manager.reset()
    redis_client.reset_memory_state()
    yield
    ws_manager.reset()
    redis_client.reset_memory_state()


async def _create_customer_and_token(
    db: AsyncSession,
    client: AsyncClient,
    *,
    phone: str = "01711002233",
    email: str = "shopper@example.com",
) -> tuple[User, str]:
    user = await customer_auth_service.register_customer(
        db,
        CustomerRegisterRequest(
            full_name="Test Shopper",
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
    return user, str(login.json()["access_token"])


def test_db_pool_settings_defaults_and_overrides() -> None:
    cfg = Settings(
        _env_file=None,  # type: ignore[call-arg]
        db_pool_size=12,
        db_max_overflow=15,
        db_pool_timeout=20,
        db_pool_recycle=900,
    )
    assert cfg.db_pool_size == 12
    assert cfg.db_max_overflow == 15
    assert cfg.db_pool_timeout == 20
    assert cfg.db_pool_recycle == 900


def test_websocket_endpoint_has_zero_db_dependency() -> None:
    """Monolith invariant: WS handler MUST NOT inject DbSession / AsyncSession."""
    sig = inspect.signature(websocket_endpoint)
    assert "db" not in sig.parameters
    for param in sig.parameters.values():
        assert "AsyncSession" not in str(param.annotation)
        assert "get_db" not in str(param.default)


@pytest.mark.asyncio
async def test_ws_ticket_endpoints_rbac_and_single_use(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    # 1. Superadmin gets staff ticket with orders & communication channels.
    staff_res = await client.post("/api/v1/auth/ws-ticket", headers=auth_headers)
    assert staff_res.status_code == 200, staff_res.text
    assert staff_res.headers.get("cache-control") == "no-store"
    body = staff_res.json()
    assert body["scope"] == "admin"
    assert body["expires_in"] == 30
    assert STAFF_ORDERS_CHANNEL in body["channels"]
    assert STAFF_COMMUNICATION_CHANNEL in body["channels"]

    # Ticket is strictly single-use via atomic consume.
    first = await redis_client.consume_ws_ticket(body["ticket"])
    assert first is not None and first["scope"] == "admin"
    second = await redis_client.consume_ws_ticket(body["ticket"])
    assert second is None

    # 2. Custom staff role with no orders/inquiries access gets only personal channel.
    admin_user = await user_service.get_by_email(db_session, "admin@implesia.com")
    assert admin_user is not None
    await permission_service.create_role(
        db_session,
        RoleCreate(label="Catalog Only", slug="catalog_only"),
        actor=admin_user,
    )
    await permission_service.update_role_permissions(
        db_session,
        [
            RolePermissionUpdateItem(
                role="catalog_only", module_key="products", access_level="read_only"
            )
        ],
        actor=admin_user,
    )
    limited_staff = await user_service.create_user(
        db_session,
        UserCreate(
            email="catalog@implesia.com",
            full_name="Catalog Staff",
            password=TEST_PASSWORD,
            role="catalog_only",
        ),
    )
    limited_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "catalog@implesia.com", "password": TEST_PASSWORD},
    )
    assert limited_login.status_code == 200
    limited_ticket = await client.post(
        "/api/v1/auth/ws-ticket",
        headers={"Authorization": f"Bearer {limited_login.json()['access_token']}"},
    )
    assert limited_ticket.status_code == 200
    assert limited_ticket.json()["channels"] == [user_channel(limited_staff.id)]

    # 3. Customer is forbidden from staff WS ticket, allowed on customer WS ticket.
    customer, cust_token = await _create_customer_and_token(db_session, client)
    cust_headers = {"Authorization": f"Bearer {cust_token}"}
    denied = await client.post("/api/v1/auth/ws-ticket", headers=cust_headers)
    assert denied.status_code == 403

    cust_ticket = await client.post("/api/v1/customer/ws-ticket", headers=cust_headers)
    assert cust_ticket.status_code == 200, cust_ticket.text
    assert cust_ticket.json()["scope"] == "customer"
    assert cust_ticket.json()["channels"] == [user_channel(customer.id)]


@pytest.mark.asyncio
async def test_ws_ticket_expiry_rejected() -> None:
    ticket = await redis_client.issue_ws_ticket(
        {"user_id": str(uuid.uuid4()), "role": "customer", "scope": "customer", "channels": []},
        ttl_seconds=0,
    )
    await asyncio.sleep(0.01)
    assert await redis_client.consume_ws_ticket(ticket) is None


def test_ws_rejects_missing_invalid_and_reused_ticket() -> None:
    sync_client = TestClient(app)

    # Missing ticket -> 4001
    with sync_client.websocket_connect("/api/v1/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == WS_CLOSE_AUTH_FAILED

    # Invalid ticket -> 4001
    with sync_client.websocket_connect("/api/v1/ws?ticket=not-a-real-ticket") as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == WS_CLOSE_AUTH_FAILED

    # Valid ticket works once, second connect with same ticket -> 4001
    uid = str(uuid.uuid4())
    ticket = asyncio.run(
        redis_client.issue_ws_ticket(
            {
                "user_id": uid,
                "role": "superadmin",
                "scope": "admin",
                "channels": [user_channel(uid), STAFF_ORDERS_CHANNEL],
            }
        )
    )
    with sync_client.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "connected"
        assert STAFF_ORDERS_CHANNEL in connected["data"]["channels"]

    with sync_client.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == WS_CLOSE_AUTH_FAILED


def test_ws_heartbeat_presence_frame_cap_and_idle_timeout() -> None:
    sync_client = TestClient(app)
    uid = str(uuid.uuid4())

    ticket = asyncio.run(
        redis_client.issue_ws_ticket(
            {
                "user_id": uid,
                "role": "customer",
                "scope": "customer",
                "channels": [user_channel(uid)],
            }
        )
    )
    with sync_client.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
        assert ws.receive_json()["type"] == "connected"
        assert asyncio.run(redis_client.is_user_online(uid)) is True

        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        assert pong["type"] == "pong"
        assert "ts" in pong

        # Oversized frame (> 4 KB) closes with 1009
        ws.send_text("x" * 5000)
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["data"]["code"] == "frame_too_large"
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == WS_CLOSE_MESSAGE_TOO_BIG

    # Presence cleared once last socket disconnects
    assert asyncio.run(redis_client.is_user_online(uid)) is False

    # Idle heartbeat timeout closes socket with 4000
    ws_manager.idle_timeout_seconds = 0.1
    ticket2 = asyncio.run(
        redis_client.issue_ws_ticket(
            {
                "user_id": uid,
                "role": "customer",
                "scope": "customer",
                "channels": [user_channel(uid)],
            }
        )
    )
    with sync_client.websocket_connect(f"/api/v1/ws?ticket={ticket2}") as ws:
        assert ws.receive_json()["type"] == "connected"
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == WS_CLOSE_IDLE_TIMEOUT


def test_ws_connection_cap_enforced_at_5_sockets() -> None:
    sync_client = TestClient(app)
    uid = str(uuid.uuid4())

    def _mint() -> str:
        return asyncio.run(
            redis_client.issue_ws_ticket(
                {
                    "user_id": uid,
                    "role": "superadmin",
                    "scope": "admin",
                    "channels": [user_channel(uid), STAFF_ORDERS_CHANNEL],
                }
            )
        )

    opened = []
    try:
        for _ in range(5):
            cm = sync_client.websocket_connect(f"/api/v1/ws?ticket={_mint()}")
            ws = cm.__enter__()
            assert ws.receive_json()["type"] == "connected"
            opened.append(cm)

        assert ws_manager.active_connection_count(uid) == 5

        # 6th connection must be rejected cleanly with code 4008
        with sync_client.websocket_connect(f"/api/v1/ws?ticket={_mint()}") as sixth:
            err = sixth.receive_json()
            assert err["type"] == "error"
            assert err["data"]["code"] == "connection_limit"
            with pytest.raises(WebSocketDisconnect) as exc_info:
                sixth.receive_json()
            assert exc_info.value.code == WS_CLOSE_TOO_MANY_CONNECTIONS
    finally:
        for cm in opened:
            cm.__exit__(None, None, None)

    assert ws_manager.active_connection_count(uid) == 0


def test_ws_rate_limiting_and_typing_relay() -> None:
    sync_client = TestClient(app)
    staff_id = str(uuid.uuid4())
    conv_id = str(uuid.uuid4())

    def _mint_staff() -> str:
        return asyncio.run(
            redis_client.issue_ws_ticket(
                {
                    "user_id": staff_id,
                    "role": "superadmin",
                    "scope": "admin",
                    "channels": [
                        user_channel(staff_id),
                        STAFF_ORDERS_CHANNEL,
                        STAFF_COMMUNICATION_CHANNEL,
                    ],
                }
            )
        )

    ws_manager.rate_limit_max_events = 3
    ws_manager.rate_limit_window_seconds = 10

    with (
        sync_client.websocket_connect(f"/api/v1/ws?ticket={_mint_staff()}") as ws1,
        sync_client.websocket_connect(f"/api/v1/ws?ticket={_mint_staff()}") as ws2,
    ):
        assert ws1.receive_json()["type"] == "connected"
        assert ws2.receive_json()["type"] == "connected"

        # Subscribe both sockets to the same conversation
        ws1.send_json({"type": "subscribe_conversation", "conversation_id": conv_id})
        sub1 = ws1.receive_json()
        assert sub1["type"] == "subscribed"
        assert sub1["data"]["channel"] == conversation_channel(conv_id)

        ws2.send_json({"type": "subscribe_conversation", "conversation_id": conv_id})
        assert ws2.receive_json()["type"] == "subscribed"

        # Typing event relays through RealtimeHub without any DB write
        ws1.send_json({"type": "typing", "conversation_id": conv_id, "is_typing": True})
        relayed_1 = ws1.receive_json()
        relayed_2 = ws2.receive_json()
        assert relayed_1["type"] == "typing"
        assert relayed_2["type"] == "typing"
        assert relayed_2["data"]["conversation_id"] == conv_id

        # 4th event within window triggers rate_limited error frame
        ws1.send_json({"type": "ping"})
        rate_err = ws1.receive_json()
        assert rate_err["type"] == "error"
        assert rate_err["data"]["code"] == "rate_limited"


@pytest.mark.asyncio
async def test_realtime_order_and_notification_events_dispatched(
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _capture(channel: str, envelope: dict[str, Any]) -> None:
        captured.append((channel, envelope))

    realtime_hub.register_dispatcher(_capture)
    try:
        customer, cust_token = await _create_customer_and_token(
            db_session,
            client,
            phone="01811223344",
            email="livebuyer@example.com",
        )
        product = Product(
            title="Realtime Silk Saree",
            slug="realtime-silk-saree",
            price=2500,
            quantity=10,
            status=StockStatus.AVAILABLE.value,
            published=True,
            content={},
        )
        db_session.add(product)
        await db_session.commit()
        await db_session.refresh(product)

        # Place an online order -> triggers order.new on rt:staff:orders
        # AND notification.created + notification.unread on rt:user:{customer.id}
        order_res = await client.post(
            "/api/v1/orders",
            headers={
                "Authorization": f"Bearer {cust_token}",
                "Idempotency-Key": "realtime-order-test-key-001",
            },
            json={
                "source": "direct",
                "items": [{"product_id": str(product.id), "quantity": 1}],
                "customer_name": "Test Shopper",
                "phone": "01811223344",
                "email": "livebuyer@example.com",
                "district": "Dhaka",
                "area": "Dhanmondi",
                "address": "House 10, Road 5, Dhanmondi, Dhaka",
                "payment_method": "cod",
            },
        )
        assert order_res.status_code == 201, order_res.text
        order_number = order_res.json()["number"]

        staff_events = [
            env for ch, env in captured if ch == STAFF_ORDERS_CHANNEL and env["type"] == "order.new"
        ]
        assert len(staff_events) == 1
        assert staff_events[0]["data"]["number"] == order_number
        assert staff_events[0]["data"]["total"] == order_res.json()["total"]

        user_ch = user_channel(customer.id)
        created_events = [
            env for ch, env in captured if ch == user_ch and env["type"] == "notification.created"
        ]
        unread_events = [
            env for ch, env in captured if ch == user_ch and env["type"] == "notification.unread"
        ]
        assert len(created_events) == 1
        assert created_events[0]["data"]["unread_count"] == 1
        assert unread_events[-1]["data"]["unread_count"] == 1

        # Mark all read -> publishes notification.unread with unread_count == 0
        captured.clear()
        mark_res = await client.post(
            "/api/v1/customer/notifications/mark-all-read",
            headers={"Authorization": f"Bearer {cust_token}"},
        )
        assert mark_res.status_code == 200
        unread_after = [
            env for ch, env in captured if ch == user_ch and env["type"] == "notification.unread"
        ]
        assert len(unread_after) == 1
        assert unread_after[0]["data"]["unread_count"] == 0

        # Create another status notification and mark single read
        captured.clear()
        order_row = await db_session.get(Order, uuid.UUID(order_res.json()["id"]))
        assert order_row is not None
        notif = await notification_service.create_order_status_notification(
            db_session, order_row, OrderStatus.CONFIRMED.value
        )
        assert notif is not None
        assert any(
            ch == user_ch and env["type"] == "notification.created" for ch, env in captured
        )

        captured.clear()
        read_res = await client.patch(
            f"/api/v1/customer/notifications/{notif.id}/read",
            headers={"Authorization": f"Bearer {cust_token}"},
        )
        assert read_res.status_code == 200
        unread_single = [
            env for ch, env in captured if ch == user_ch and env["type"] == "notification.unread"
        ]
        assert len(unread_single) == 1
        assert unread_single[0]["data"]["unread_count"] == 0
    finally:
        realtime_hub.unregister_dispatcher(_capture)


@pytest.mark.asyncio
async def test_realtime_publish_failure_never_breaks_order_creation(
    db_session: AsyncSession,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(channel: str, envelope: dict[str, Any]) -> None:
        raise RuntimeError("simulated dispatcher failure")

    realtime_hub.register_dispatcher(_boom)
    try:
        product = Product(
            title="Resilient Cotton Kurta",
            slug="resilient-cotton-kurta",
            price=1500,
            quantity=5,
            status=StockStatus.AVAILABLE.value,
            published=True,
            content={},
        )
        db_session.add(product)
        await db_session.commit()
        await db_session.refresh(product)

        res = await client.post(
            "/api/v1/orders",
            headers={"Idempotency-Key": "resilient-order-key-001"},
            json={
                "source": "direct",
                "items": [{"product_id": str(product.id), "quantity": 1}],
                "customer_name": "Guest Buyer",
                "phone": "01911223344",
                "district": "Dhaka",
                "area": "Uttara",
                "address": "Sector 7, Road 12, Uttara, Dhaka",
                "payment_method": "cod",
            },
        )
        assert res.status_code == 201, res.text
    finally:
        realtime_hub.unregister_dispatcher(_boom)
        monkeypatch.undo()
