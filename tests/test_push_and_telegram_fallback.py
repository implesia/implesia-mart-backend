"""Phase 23 tests: W3C Web Push (VAPID) subscriptions, 410 cleanup, and Telegram chat fallback."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from pywebpush import WebPushException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings, settings
from app.core.security import hash_password
from app.models.communication import Conversation, ConversationStatus, ConversationType, Message
from app.models.push_subscription import PushSubscription
from app.models.user import User, UserRole
from app.services import push_service, telegram_notify


async def _create_customer_headers(
    client: AsyncClient,
    db_session: AsyncSession,
    *,
    phone: str = "01755551111",
    email: str = "push-cust@implesia.com",
) -> tuple[User, dict[str, str]]:
    password = "customer-passphrase-123"
    user = User(
        email=email,
        phone=phone,
        full_name="Push Customer",
        password_hash=hash_password(password),
        role=UserRole.CUSTOMER.value,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    login = await client.post(
        "/api/v1/customer/auth/login",
        json={"identifier": phone, "password": password},
    )
    assert login.status_code == 200, login.text
    return user, {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_push_subscription_upsert_cap_and_delete(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    # Public VAPID endpoint returns disabled cleanly when keys are unset
    key_res = await client.get("/api/v1/push/vapid-public-key")
    assert key_res.status_code == 200
    assert key_res.json()["enabled"] is False

    # Upsert 12 admin subscriptions -> cap at MAX_DEVICES_PER_USER_SCOPE (10)
    for idx in range(12):
        res = await client.post(
            "/api/v1/auth/push/subscribe",
            headers=auth_headers,
            json={
                "endpoint": f"https://push.example.com/admin/{idx}",
                "keys": {"p256dh": f"p256dh-key-value-{idx:02d}", "auth": f"auth-key-{idx:02d}"},
                "user_agent": f"Chrome/{idx}",
            },
        )
        assert res.status_code == 201, res.text

    count = await db_session.scalar(
        select(func.count(PushSubscription.id)).where(PushSubscription.scope == "admin")
    )
    assert count == push_service.MAX_DEVICES_PER_USER_SCOPE

    # Delete one endpoint
    del_res = await client.request(
        "DELETE",
        "/api/v1/auth/push/subscribe",
        headers=auth_headers,
        json={"endpoint": "https://push.example.com/admin/11"},
    )
    assert del_res.status_code == 204
    after_count = await db_session.scalar(
        select(func.count(PushSubscription.id)).where(PushSubscription.scope == "admin")
    )
    assert after_count == push_service.MAX_DEVICES_PER_USER_SCOPE - 1

    # Customer subscription works independently on customer scope and cannot use admin endpoint
    _cust, cust_headers = await _create_customer_headers(client, db_session)
    assert (
        await client.post(
            "/api/v1/auth/push/subscribe",
            headers=cust_headers,
            json={
                "endpoint": "https://push.example.com/cust/blocked",
                "keys": {"p256dh": "p256dh-key-customer-1", "auth": "auth-cust-1"},
            },
        )
    ).status_code == 403

    cust_sub = await client.post(
        "/api/v1/customer/push/subscribe",
        headers=cust_headers,
        json={
            "endpoint": "https://push.example.com/cust/1",
            "keys": {"p256dh": "p256dh-key-customer-1", "auth": "auth-cust-1"},
        },
    )
    assert cust_sub.status_code == 201, cust_sub.text
    assert cust_sub.json()["scope"] == "customer"


@pytest.mark.asyncio
async def test_dead_410_gone_subscription_cleanup(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cust, cust_headers = await _create_customer_headers(
        client, db_session, phone="01755552222", email="gone-cust@implesia.com"
    )
    for ep in ("https://push.example.com/gone", "https://push.example.com/alive"):
        res = await client.post(
            "/api/v1/customer/push/subscribe",
            headers=cust_headers,
            json={"endpoint": ep, "keys": {"p256dh": "p256dh-key-123456", "auth": "auth-123456"}},
        )
        assert res.status_code == 201

    monkeypatch.setattr(settings, "vapid_public_key", "test-pub-key")
    monkeypatch.setattr(settings, "vapid_private_key", SecretStr("test-priv-key"))

    def fake_deliver(info: dict[str, object], _payload_json: str) -> None:
        if info["endpoint"] == "https://push.example.com/gone":
            exc = WebPushException("Gone")
            exc.response = SimpleNamespace(status_code=410)
            raise exc

    bind = AsyncEngine(db_session.get_bind())
    factory = async_sessionmaker(bind=bind, class_=AsyncSession, expire_on_commit=False)

    with patch.object(push_service, "_deliver_single", side_effect=fake_deliver):
        sent = await push_service.send_push_to_users(
            [cust.id],
            "customer",
            push_service.build_push_payload(
                title="Test",
                body="Hello",
                url="/dashboard/messages",
                tag="test-tag",
                scope="customer",
            ),
            session_factory=factory,
        )

    assert sent == 1
    remaining = list(
        (
            await db_session.scalars(
                select(PushSubscription.endpoint).where(PushSubscription.user_id == cust.id)
            )
        ).all()
    )
    assert remaining == ["https://push.example.com/alive"]


@pytest.mark.asyncio
async def test_internal_note_never_pushes_to_customer_but_public_reply_does(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cust, _cust_headers = await _create_customer_headers(
        client, db_session, phone="01755553333", email="note-cust@implesia.com"
    )
    conv = Conversation(
        type=ConversationType.CUSTOMER_SUPPORT.value,
        status=ConversationStatus.OPEN.value,
        subject="Order help",
        customer_id=cust.id,
    )
    db_session.add(conv)
    await db_session.commit()
    await db_session.refresh(conv)

    monkeypatch.setattr(settings, "vapid_public_key", "test-pub-key")
    monkeypatch.setattr(settings, "vapid_private_key", SecretStr("test-priv-key"))

    with patch.object(push_service, "schedule_push_to_users") as mock_schedule:
        # 1. Internal note -> MUST NOT push to customer
        note_res = await client.post(
            f"/api/v1/admin/communication/conversations/{conv.id}/messages",
            headers=auth_headers,
            json={"body": "Internal staff memo", "is_internal_note": True},
        )
        assert note_res.status_code == 201, note_res.text
        mock_schedule.assert_not_called()

        # 2. Public reply -> MUST schedule customer push with canQuickReply=True
        reply_res = await client.post(
            f"/api/v1/admin/communication/conversations/{conv.id}/messages",
            headers=auth_headers,
            json={"body": "Your order is on the way!", "is_internal_note": False},
        )
        assert reply_res.status_code == 201, reply_res.text
        mock_schedule.assert_called_once()
        args = mock_schedule.call_args.args
        assert args[1] == [cust.id]
        assert args[2] == "customer"
        assert args[3]["canQuickReply"] is True
        assert args[3]["conversationId"] == str(conv.id)


@pytest.mark.asyncio
async def test_telegram_unanswered_chat_fallback_dedupes_and_skips_when_replied(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client, auth_headers
    cust = User(
        email="tg-cust@implesia.com",
        phone="01755554444",
        full_name="Telegram Fallback Customer",
        password_hash=hash_password("customer-passphrase-123"),
        role=UserRole.CUSTOMER.value,
        is_active=True,
    )
    db_session.add(cust)
    await db_session.commit()
    await db_session.refresh(cust)

    conv_unanswered = Conversation(
        type=ConversationType.CUSTOMER_SUPPORT.value,
        status=ConversationStatus.OPEN.value,
        subject="Unanswered chat",
        customer_id=cust.id,
    )
    conv_replied = Conversation(
        type=ConversationType.CUSTOMER_SUPPORT.value,
        status=ConversationStatus.OPEN.value,
        subject="Replied chat",
        customer_id=cust.id,
    )
    db_session.add_all([conv_unanswered, conv_replied])
    await db_session.commit()
    await db_session.refresh(conv_unanswered)
    await db_session.refresh(conv_replied)

    msg_time = datetime.now(UTC) - timedelta(seconds=10)
    db_session.add(
        Message(
            conversation_id=conv_replied.id,
            sender_id=None,
            sender_role="editor",
            body="Staff replied already",
            is_internal_note=False,
            created_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr("fake-token"))
    monkeypatch.setattr(settings, "telegram_chat_ids", ["-100123456"])
    monkeypatch.setattr(settings, "telegram_chat_fallback_enabled", True)
    monkeypatch.setattr(settings, "admin_base_url", "https://mart.implesia.com")

    bind = AsyncEngine(db_session.get_bind())
    factory = async_sessionmaker(bind=bind, class_=AsyncSession, expire_on_commit=False)

    with patch.object(telegram_notify, "send_message", new_callable=AsyncMock) as mock_deliver:
        # 1. Unanswered conversation -> sends ONE Telegram alert
        sent_first = await telegram_notify.run_unanswered_chat_fallback(
            conversation_id=conv_unanswered.id,
            message_created_at=msg_time,
            customer_name=cust.full_name,
            customer_phone=cust.phone,
            order_number="IM-9999",
            excerpt="Hello, anyone there?",
            delay_seconds=0,
            session_factory=factory,
        )
        assert sent_first is True
        assert mock_deliver.await_count == 1
        sent_text = mock_deliver.call_args.args[1]
        assert "Telegram Fallback Customer" in sent_text
        assert "IM-9999" in sent_text
        assert f"/admin/communication?id={conv_unanswered.id}" in sent_text

        # 2. Second trigger for same conversation within TTL -> deduplicated (no spam)
        sent_dup = await telegram_notify.run_unanswered_chat_fallback(
            conversation_id=conv_unanswered.id,
            message_created_at=msg_time,
            customer_name=cust.full_name,
            customer_phone=cust.phone,
            order_number="IM-9999",
            excerpt="Still waiting",
            delay_seconds=0,
            session_factory=factory,
        )
        assert sent_dup is False
        assert mock_deliver.await_count == 1

        # 3. Conversation where staff already replied -> skipped cleanly
        sent_replied = await telegram_notify.run_unanswered_chat_fallback(
            conversation_id=conv_replied.id,
            message_created_at=msg_time,
            customer_name=cust.full_name,
            customer_phone=cust.phone,
            order_number=None,
            excerpt="Thanks!",
            delay_seconds=0,
            session_factory=factory,
        )
        assert sent_replied is False
        assert mock_deliver.await_count == 1


_ORDER_CHATS = ["111", "-100222"]
_FALLBACK_CHATS = ["-100333"]
_BOT = "test-bot-token"


class _TelegramPosts:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, object]]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded = self

        class _Client:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def post(
                self, url: str, *, json: dict[str, object] | None = None
            ) -> SimpleNamespace:
                recorded.posts.append((url, json or {}))
                return SimpleNamespace(status_code=200, headers={})

        monkeypatch.setattr(telegram_notify.httpx, "AsyncClient", _Client)


def _posted_chat_ids(posts: list[tuple[str, dict[str, object]]]) -> list[object]:
    return [body.get("chat_id") for _url, body in posts]


def test_telegram_chat_fallback_chat_ids_parse_like_order_chats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = " 111 , -100222 ,,"
    orders = Settings(telegram_chat_ids=raw)
    fallback = Settings(telegram_chat_fallback_chat_ids=raw)
    assert fallback.telegram_chat_fallback_chat_ids == orders.telegram_chat_ids
    assert orders.telegram_chat_ids == ["111", "-100222"]
    assert Settings(telegram_chat_fallback_chat_ids="").telegram_chat_fallback_chat_ids == []
    assert Settings(telegram_chat_fallback_chat_ids="   ").telegram_chat_fallback_chat_ids == []
    monkeypatch.delenv("TELEGRAM_CHAT_FALLBACK_CHAT_IDS", raising=False)
    omitted = Settings(_env_file=None)
    assert omitted.telegram_chat_fallback_chat_ids == []


async def _open_conversation(db_session: AsyncSession, *, email: str, phone: str) -> Conversation:
    customer = User(
        email=email,
        phone=phone,
        full_name="Fallback Chat Customer",
        password_hash=hash_password("customer-passphrase-123"),
        role=UserRole.CUSTOMER.value,
        is_active=True,
    )
    db_session.add(customer)
    await db_session.commit()
    await db_session.refresh(customer)
    conversation = Conversation(
        type=ConversationType.CUSTOMER_SUPPORT.value,
        status=ConversationStatus.OPEN.value,
        subject="Unanswered chat",
        customer_id=customer.id,
    )
    db_session.add(conversation)
    await db_session.commit()
    await db_session.refresh(conversation)
    return conversation


def _session_factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    bind = AsyncEngine(db_session.get_bind())
    return async_sessionmaker(bind=bind, class_=AsyncSession, expire_on_commit=False)


def _arm_telegram(monkeypatch: pytest.MonkeyPatch, fallback_ids: list[str]) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr(_BOT))
    monkeypatch.setattr(settings, "telegram_chat_ids", list(_ORDER_CHATS))
    monkeypatch.setattr(settings, "telegram_chat_fallback_chat_ids", list(fallback_ids))
    monkeypatch.setattr(settings, "telegram_chat_fallback_enabled", True)


@pytest.mark.asyncio
async def test_chat_fallback_uses_dedicated_chats_and_orders_stay_on_order_chats(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = await _open_conversation(
        db_session, email="tg-dedicated@implesia.com", phone="01755555501"
    )
    _arm_telegram(monkeypatch, _FALLBACK_CHATS)
    recorded = _TelegramPosts()
    recorded.install(monkeypatch)

    sent = await telegram_notify.run_unanswered_chat_fallback(
        conversation_id=conversation.id,
        message_created_at=datetime.now(UTC),
        customer_name="Fallback Chat Customer",
        customer_phone="01755555501",
        order_number=None,
        excerpt="Need help",
        delay_seconds=0,
        session_factory=_session_factory(db_session),
    )

    assert sent is True
    assert _posted_chat_ids(recorded.posts) == _FALLBACK_CHATS
    fallback_urls = {url for url, _body in recorded.posts}
    assert fallback_urls == {f"https://api.telegram.org/bot{_BOT}/sendMessage"}

    recorded.posts.clear()
    await telegram_notify.send_message("IM-1001", "<b>New order IM-1001</b>")
    assert _posted_chat_ids(recorded.posts) == _ORDER_CHATS
    assert {url for url, _body in recorded.posts} == fallback_urls


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["empty", "unset"])
async def test_chat_fallback_uses_order_chats_when_fallback_ids_missing(
    mode: str,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if mode == "unset":
        monkeypatch.delenv("TELEGRAM_CHAT_FALLBACK_CHAT_IDS", raising=False)
        fallback_ids = list(Settings(_env_file=None).telegram_chat_fallback_chat_ids)
    else:
        blank = Settings(telegram_chat_fallback_chat_ids="")
        fallback_ids = list(blank.telegram_chat_fallback_chat_ids)
    assert fallback_ids == []

    phone = "01755555502" if mode == "empty" else "01755555503"
    conversation = await _open_conversation(
        db_session,
        email=f"tg-{mode}@implesia.com",
        phone=phone,
    )
    _arm_telegram(monkeypatch, fallback_ids)
    recorded = _TelegramPosts()
    recorded.install(monkeypatch)

    sent = await telegram_notify.run_unanswered_chat_fallback(
        conversation_id=conversation.id,
        message_created_at=datetime.now(UTC),
        customer_name="Fallback Chat Customer",
        customer_phone=phone,
        order_number=None,
        excerpt="Still waiting",
        delay_seconds=0,
        session_factory=_session_factory(db_session),
    )

    assert sent is True
    assert _posted_chat_ids(recorded.posts) == _ORDER_CHATS
