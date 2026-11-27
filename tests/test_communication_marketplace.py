"""Phase 29: Marketplace multi-role communication channels, avatars, presence & summary."""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication import (
    Conversation,
    ConversationStatus,
    ConversationType,
    Message,
)
from app.models.user import User
from app.schemas.customer import CustomerRegisterRequest
from app.services import customer_auth_service
from app.services.realtime_hub import STAFF_COMMUNICATION_CHANNEL, realtime_hub
from app.services.redis_client import redis_client
from app.services.ws_manager import ws_manager

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_0117_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "0117_communication_dropshipper_channels.py"
)


@pytest.fixture(autouse=True)
def _reset_realtime() -> Any:
    redis_client.reset_memory_state()
    ws_manager.reset()
    yield
    redis_client.reset_memory_state()
    ws_manager.reset()


def _load_0117_module() -> Any:
    spec = importlib.util.spec_from_file_location("mig_0117", MIGRATION_0117_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _make_user(
    db: AsyncSession,
    *,
    name: str,
    phone: str,
    email: str,
    avatar_url: str | None = None,
) -> User:
    user = await customer_auth_service.register_customer(
        db,
        CustomerRegisterRequest(
            full_name=name,
            phone=phone,
            email=email,
            password="MarketplacePassword123!",
        ),
    )
    if avatar_url is not None:
        user.avatar_url = avatar_url
        await db.commit()
        await db.refresh(user)
    return user


def test_migration_0117_allows_dropshipper_channels_and_downgrades(tmp_path: Path) -> None:
    mod = _load_0117_module()
    assert mod.revision == "0117"
    assert mod.down_revision == "0116"

    db_file = tmp_path / "mig0117.sqlite3"
    engine = sa.create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE users (id CHAR(36) PRIMARY KEY)"))
            conn.execute(
                sa.text(
                    "CREATE TABLE conversations ("
                    "id CHAR(36) PRIMARY KEY, "
                    "type VARCHAR(24) NOT NULL, "
                    "last_message_at DATETIME, "
                    "CONSTRAINT ck_conversations_type_known "
                    "CHECK (type IN ('customer_support', 'seller_support', 'customer_seller'))"
                    ")"
                )
            )
            uid = str(uuid.uuid4())
            conn.execute(sa.text("INSERT INTO users (id) VALUES (:id)"), {"id": uid})

            # Before upgrade, dropshipper_support is rejected by the CHECK constraint.
            with pytest.raises(sa.exc.IntegrityError):
                conn.execute(
                    sa.text(
                        "INSERT INTO conversations (id, type) VALUES (:id, 'dropshipper_support')"
                    ),
                    {"id": str(uuid.uuid4())},
                )

        with engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mod.upgrade()

            cols = {c["name"] for c in sa.inspect(conn).get_columns("conversations")}
            assert "dropshipper_id" in cols
            idx_names = {i["name"] for i in sa.inspect(conn).get_indexes("conversations")}
            assert "ix_conversations_dropshipper_id" in idx_names
            assert "ix_conversations_dropshipper_last_msg" in idx_names

            # Both new dropshipper channel types now succeed.
            for ch_type in ("dropshipper_support", "customer_dropshipper"):
                conn.execute(
                    sa.text(
                        "INSERT INTO conversations (id, type, dropshipper_id) "
                        "VALUES (:id, :t, :did)"
                    ),
                    {"id": str(uuid.uuid4()), "t": ch_type, "did": uid},
                )
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_sender_avatar_url_in_rest_and_ws_and_batched_presence(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    customer = await _make_user(
        db_session,
        name="Avatar Customer",
        phone="01720001111",
        email="avatar.cust@example.com",
        avatar_url="media/avatars/cust.webp",
    )
    dropshipper = await _make_user(
        db_session,
        name="Dropshipper One",
        phone="01720002222",
        email="drop.one@example.com",
        avatar_url="/media/avatars/drop.webp",
    )

    now = datetime.now(UTC)
    conv = Conversation(
        type=ConversationType.DROPSHIPPER_SUPPORT.value,
        dropshipper_id=dropshipper.id,
        subject="Wholesale Stock Inquiry",
        status=ConversationStatus.OPEN.value,
        last_message_at=now,
        last_message_preview="Need bulk pricing",
    )
    db_session.add(conv)
    await db_session.flush()
    db_session.add(
        Message(
            conversation_id=conv.id,
            sender_id=dropshipper.id,
            sender_role="customer",
            body="Need bulk pricing",
            created_at=now,
        )
    )
    await db_session.commit()

    # Mark dropshipper online in Redis presence
    await redis_client.set_presence(str(dropshipper.id), ttl_seconds=60)

    # Admin list returns hydrated dropshipper + avatar + is_online=True
    listed = await client.get(
        "/api/v1/admin/communication/conversations",
        headers=auth_headers,
        params={"channel_group": "dropshipper"},
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["dropshipper_id"] == str(dropshipper.id)
    assert items[0]["dropshipper"]["avatar_url"] == "/media/avatars/drop.webp"
    assert items[0]["is_online"] is True

    # REST messages include sender_avatar_url
    msgs_res = await client.get(
        f"/api/v1/admin/communication/conversations/{conv.id}/messages",
        headers=auth_headers,
    )
    assert msgs_res.status_code == 200, msgs_res.text
    msg_items = msgs_res.json()["items"]
    assert len(msg_items) == 1
    assert msg_items[0]["sender_avatar_url"] == "/media/avatars/drop.webp"

    # Capture real-time WS message.created event payload to verify sender_avatar_url
    captured: list[tuple[str, str, dict[str, Any]]] = []
    original_publish = realtime_hub.publish

    async def _spy_publish(channel: str, event: str, data: dict[str, Any]) -> None:
        captured.append((channel, event, data))
        await original_publish(channel, event, data)

    realtime_hub.publish = _spy_publish  # type: ignore[method-assign]
    try:
        # Give staff an avatar so we verify staff sender_avatar_url too
        me = await client.get("/api/v1/auth/me", headers=auth_headers)
        staff_id = uuid.UUID(me.json()["id"])
        staff_row = await db_session.get(User, staff_id)
        assert staff_row is not None
        staff_row.avatar_url = "/media/avatars/staff.png"
        await db_session.commit()

        sent = await client.post(
            f"/api/v1/admin/communication/conversations/{conv.id}/messages",
            headers=auth_headers,
            json={"body": "Bulk tier pricing sent!"},
        )
        assert sent.status_code == 201, sent.text
        assert sent.json()["sender_avatar_url"] == "/media/avatars/staff.png"
    finally:
        realtime_hub.publish = original_publish  # type: ignore[method-assign]

    staff_events = [
        data
        for ch, ev, data in captured
        if ch == STAFF_COMMUNICATION_CHANNEL and ev == "message.created"
    ]
    assert len(staff_events) == 1
    assert staff_events[0]["sender_avatar_url"] == "/media/avatars/staff.png"

    # Relative customer avatar without leading slash is normalized too
    cust_conv = Conversation(
        type=ConversationType.CUSTOMER_SUPPORT.value,
        customer_id=customer.id,
        subject="Order help",
        status=ConversationStatus.OPEN.value,
        last_message_at=now,
        last_message_preview="Hi",
    )
    db_session.add(cust_conv)
    await db_session.commit()

    cust_list = await client.get(
        "/api/v1/admin/communication/conversations",
        headers=auth_headers,
        params={"channel_group": "customer"},
    )
    assert cust_list.status_code == 200
    assert cust_list.json()["items"][0]["customer"]["avatar_url"] == "/media/avatars/cust.webp"
    assert cust_list.json()["items"][0]["is_online"] is False


@pytest.mark.asyncio
async def test_channel_group_filtering_and_per_channel_summary(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    cust = await _make_user(
        db_session,
        name="C1",
        phone="01730001111",
        email="c1@example.com",
    )
    seller = await _make_user(
        db_session,
        name="S1",
        phone="01730002222",
        email="s1@example.com",
    )
    drop = await _make_user(
        db_session,
        name="D1",
        phone="01730003333",
        email="d1@example.com",
    )
    now = datetime.now(UTC)

    c_cust = Conversation(
        type=ConversationType.CUSTOMER_SUPPORT.value,
        customer_id=cust.id,
        subject="Customer thread",
        status=ConversationStatus.OPEN.value,
        last_message_at=now,
    )
    c_seller_1 = Conversation(
        type=ConversationType.SELLER_SUPPORT.value,
        seller_id=seller.id,
        subject="Seller support thread",
        status=ConversationStatus.OPEN.value,
        last_message_at=now,
    )
    c_seller_2 = Conversation(
        type=ConversationType.CUSTOMER_SELLER.value,
        customer_id=cust.id,
        seller_id=seller.id,
        subject="Customer-Seller thread",
        status=ConversationStatus.PENDING.value,
        last_message_at=now,
    )
    c_drop_1 = Conversation(
        type=ConversationType.DROPSHIPPER_SUPPORT.value,
        dropshipper_id=drop.id,
        subject="Dropshipper support",
        status=ConversationStatus.OPEN.value,
        last_message_at=now,
    )
    c_drop_2 = Conversation(
        type=ConversationType.CUSTOMER_DROPSHIPPER.value,
        customer_id=cust.id,
        dropshipper_id=drop.id,
        subject="Customer-Dropshipper thread",
        status=ConversationStatus.OPEN.value,
        last_message_at=now,
    )
    db_session.add_all([c_cust, c_seller_1, c_seller_2, c_drop_1, c_drop_2])
    await db_session.flush()

    # Add unread messages: 2 on customer, 1 on seller_support, 3 across dropshipper (2 + 1)
    db_session.add_all(
        [
            Message(
                conversation_id=c_cust.id,
                sender_id=cust.id,
                sender_role="customer",
                body="Cust msg 1",
                created_at=now,
            ),
            Message(
                conversation_id=c_cust.id,
                sender_id=cust.id,
                sender_role="customer",
                body="Cust msg 2",
                created_at=now,
            ),
            Message(
                conversation_id=c_seller_1.id,
                sender_id=seller.id,
                sender_role="seller",
                body="Seller msg 1",
                created_at=now,
            ),
            Message(
                conversation_id=c_drop_1.id,
                sender_id=drop.id,
                sender_role="dropshipper",
                body="Drop msg 1",
                created_at=now,
            ),
            Message(
                conversation_id=c_drop_1.id,
                sender_id=drop.id,
                sender_role="dropshipper",
                body="Drop msg 2",
                created_at=now,
            ),
            Message(
                conversation_id=c_drop_2.id,
                sender_id=cust.id,
                sender_role="customer",
                body="Drop cust msg 1",
                created_at=now,
            ),
        ]
    )
    await db_session.commit()

    # Verify channel_group filters
    res_all = await client.get(
        "/api/v1/admin/communication/conversations",
        headers=auth_headers,
        params={"channel_group": "all"},
    )
    assert res_all.status_code == 200
    assert res_all.json()["total"] == 5

    res_cust = await client.get(
        "/api/v1/admin/communication/conversations",
        headers=auth_headers,
        params={"channel_group": "customer"},
    )
    assert res_cust.status_code == 200
    assert {i["id"] for i in res_cust.json()["items"]} == {str(c_cust.id)}

    res_seller = await client.get(
        "/api/v1/admin/communication/conversations",
        headers=auth_headers,
        params={"channel_group": "seller"},
    )
    assert res_seller.status_code == 200
    assert {i["id"] for i in res_seller.json()["items"]} == {
        str(c_seller_1.id),
        str(c_seller_2.id),
    }

    res_drop = await client.get(
        "/api/v1/admin/communication/conversations",
        headers=auth_headers,
        params={"channel_group": "dropshipper"},
    )
    assert res_drop.status_code == 200
    assert {i["id"] for i in res_drop.json()["items"]} == {
        str(c_drop_1.id),
        str(c_drop_2.id),
    }

    # Verify summary by_channel counts
    summary_res = await client.get(
        "/api/v1/admin/communication/summary",
        headers=auth_headers,
    )
    assert summary_res.status_code == 200, summary_res.text
    summary = summary_res.json()
    assert summary["open_count"] == 4
    assert summary["unread_conversations_count"] == 4
    assert summary["total_unread_messages"] == 6

    by_ch = summary["by_channel"]
    assert by_ch["customer"] == {
        "open_count": 1,
        "unread_conversations": 1,
        "total_unread_messages": 2,
    }
    assert by_ch["seller"] == {
        "open_count": 1,
        "unread_conversations": 1,
        "total_unread_messages": 1,
    }
    assert by_ch["dropshipper"] == {
        "open_count": 2,
        "unread_conversations": 2,
        "total_unread_messages": 3,
    }


@pytest.mark.asyncio
async def test_presence_tracks_real_online_and_last_seen_at(
    db_session: AsyncSession,
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    user = await _make_user(
        db_session,
        name="Presence Customer",
        phone="01729998877",
        email="presence.cust@example.com",
    )
    conv = Conversation(
        type=ConversationType.CUSTOMER_SUPPORT.value,
        customer_id=user.id,
        subject="Presence check",
        status=ConversationStatus.OPEN.value,
        last_message_at=datetime.now(UTC),
        last_message_preview="Hi",
    )
    db_session.add(conv)
    await db_session.commit()

    # 1. Online -> is_online=True and last_seen_at populated
    await redis_client.set_presence(str(user.id), ttl_seconds=60)
    res_online = await client.get(
        f"/api/v1/admin/communication/conversations/{conv.id}",
        headers=auth_headers,
    )
    assert res_online.status_code == 200
    body_online = res_online.json()
    assert body_online["is_online"] is True
    assert body_online["customer_is_online"] is True
    assert body_online["last_seen_at"] is not None

    # 2. Disconnect -> is_online=False and exact disconnect last_seen_at preserved
    offline_iso = await redis_client.clear_presence(str(user.id))
    assert offline_iso
    res_offline = await client.get(
        f"/api/v1/admin/communication/conversations/{conv.id}",
        headers=auth_headers,
    )
    assert res_offline.status_code == 200
    body_offline = res_offline.json()
    assert body_offline["is_online"] is False
    assert body_offline["customer_is_online"] is False
    assert body_offline["last_seen_at"] is not None

    # 3. Also exposed in paginated list endpoint
    list_res = await client.get(
        "/api/v1/admin/communication/conversations",
        headers=auth_headers,
    )
    assert list_res.status_code == 200
    matched = next(i for i in list_res.json()["items"] if i["id"] == str(conv.id))
    assert matched["is_online"] is False
    assert matched["last_seen_at"] is not None
