"""Staff new-order feed and Telegram alerts. HTTP is mocked; nothing is sent."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import LOW_STOCK_THRESHOLD, settings
from app.models.order import Order
from app.schemas.order import NewOrderQuery
from app.services import telegram_notify
from tests.test_orders import SHIPPING, _key
from tests.test_products import _create
from tests.test_site_footer import JPEG

_TOKEN = "test-bot-token"
_CHATS = ["111", "-100222"]
_BASE = "https://admin.example"


def _enable(
    monkeypatch: pytest.MonkeyPatch,
    *,
    chats: list[str] | None = None,
    cancelled: bool = False,
    low_stock: bool = False,
) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr(_TOKEN))
    monkeypatch.setattr(settings, "telegram_chat_ids", list(_CHATS if chats is None else chats))
    monkeypatch.setattr(settings, "admin_base_url", _BASE)
    monkeypatch.setattr(settings, "telegram_notify_order_cancelled", cancelled)
    monkeypatch.setattr(settings, "telegram_notify_low_stock", low_stock)


def _disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", SecretStr(""))
    monkeypatch.setattr(settings, "telegram_chat_ids", [])
    monkeypatch.setattr(settings, "admin_base_url", "")
    monkeypatch.setattr(settings, "telegram_notify_order_cancelled", False)
    monkeypatch.setattr(settings, "telegram_notify_low_stock", False)


class _Response:
    def __init__(self, status_code: int, *, retry_after: float | None = None) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self._retry_after = retry_after
        if retry_after is not None:
            self.headers["retry-after"] = str(retry_after)

    def json(self) -> dict[str, Any]:
        if self._retry_after is None:
            return {}
        return {"parameters": {"retry_after": self._retry_after}}


class _Recorder:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.statuses: list[int] = []
        self.retry_after: float | None = None
        self.error: Exception | None = None
        self.timeouts: list[object] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = self

        class _Client:
            def __init__(self, *_args: object, **kwargs: object) -> None:
                recorder.timeouts.append(kwargs.get("timeout"))

            async def __aenter__(self) -> "_Client":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def post(self, url: str, *, json: dict[str, Any] | None = None) -> _Response:
                recorder.posts.append((url, json or {}))
                if recorder.error is not None:
                    raise recorder.error
                status = recorder.statuses.pop(0) if recorder.statuses else 200
                return _Response(status, retry_after=recorder.retry_after)

        monkeypatch.setattr(telegram_notify.httpx, "AsyncClient", _Client)

        async def _sleep(_delay: float) -> None:
            recorder.sleeps.append(_delay)

        recorder.sleeps: list[float] = []
        monkeypatch.setattr(telegram_notify.asyncio, "sleep", _sleep)


def _logs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []

    def _record(event: str, **kwargs: Any) -> None:
        found.append((event, kwargs))

    monkeypatch.setattr(telegram_notify.logger, "error", _record)
    monkeypatch.setattr(telegram_notify.logger, "info", _record)
    return found


def _order(product_id: str, **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "source": "direct",
        "items": [{"product_id": product_id, "quantity": 1}],
        **SHIPPING,
    }
    body.update(extra)
    return body


async def _place(
    client: AsyncClient,
    product_id: str,
    *,
    key: str | None = None,
    **extra: object,
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": key or _key()},
        json=_order(product_id, **extra),
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _viewer_headers(client: AsyncClient, auth_headers: dict[str, str]) -> dict[str, str]:
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "order-feed-viewer@implesia.com",
            "full_name": "Order Feed Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "order-feed-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_new_order_query_defaults_and_limit() -> None:
    assert NewOrderQuery().limit == 20
    assert NewOrderQuery(limit=50).limit == 50
    with pytest.raises(ValidationError):
        NewOrderQuery(limit=51)
    with pytest.raises(ValidationError):
        NewOrderQuery(limit=0)
    naive = NewOrderQuery(since=datetime(2026, 11, 10, 8, 0))
    assert naive.since is not None
    assert naive.since.tzinfo is UTC


async def test_new_orders_feed_is_staff_only_and_cursor_shaped(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    anonymous = await client.get("/api/v1/admin/orders/new")
    assert anonymous.status_code == 401

    cart_only = await client.get("/api/v1/admin/orders/new", headers={"X-Cart-Token": "c" * 32})
    assert cart_only.status_code == 401

    garbage = await client.get(
        "/api/v1/admin/orders/new", headers={"Authorization": "Bearer not-a-staff-token"}
    )
    assert garbage.status_code == 401

    product = await _create(client, auth_headers, title="Feed Lamp", price=500, quantity=5)
    first = await _place(client, product["id"], customer_name="Older Buyer")
    second = await _place(client, product["id"], customer_name="Newer Buyer")

    older = await db_session.get(Order, uuid.UUID(first["id"]))
    newer = await db_session.get(Order, uuid.UUID(second["id"]))
    assert older is not None and newer is not None
    now = datetime.now(UTC)
    older.created_at = now - timedelta(hours=25)
    newer.created_at = now - timedelta(minutes=5)
    await db_session.commit()

    viewer = await _viewer_headers(client, auth_headers)
    feed = await client.get("/api/v1/admin/orders/new", headers=viewer)
    assert feed.status_code == 200, feed.text
    assert feed.headers["cache-control"] == "no-store"
    body = feed.json()
    assert set(body) == {"now", "items"}
    assert [item["customer_name"] for item in body["items"]] == ["Newer Buyer"]
    item = body["items"][0]
    assert set(item) == {
        "id",
        "number",
        "customer_name",
        "total",
        "payment_method",
        "created_at",
    }
    assert item["id"] == second["id"]
    assert item["number"] == second["number"]
    assert item["number"].startswith("IM-")
    assert item["total"] == second["total"]
    assert item["payment_method"] == "cod"
    parsed_now = datetime.fromisoformat(body["now"])
    parsed_created = datetime.fromisoformat(item["created_at"])
    assert parsed_now.utcoffset() == timedelta(0)
    assert parsed_created.utcoffset() == timedelta(0)
    assert parsed_created <= parsed_now

    limited = await client.get(
        "/api/v1/admin/orders/new",
        headers=auth_headers,
        params={"since": (now - timedelta(hours=30)).isoformat(), "limit": 1},
    )
    assert limited.status_code == 200, limited.text
    assert [row["id"] for row in limited.json()["items"]] == [second["id"]]

    both = await client.get(
        "/api/v1/admin/orders/new",
        headers=auth_headers,
        params={"since": (now - timedelta(hours=30)).isoformat(), "limit": 2},
    )
    assert [row["customer_name"] for row in both.json()["items"]] == [
        "Newer Buyer",
        "Older Buyer",
    ]

    exact = await client.get(
        "/api/v1/admin/orders/new",
        headers=viewer,
        params={"since": newer.created_at.isoformat()},
    )
    assert exact.status_code == 200, exact.text
    assert all(row["id"] != second["id"] for row in exact.json()["items"])
    assert all(row["id"] != first["id"] for row in exact.json()["items"])

    too_many = await client.get("/api/v1/admin/orders/new", headers=viewer, params={"limit": 51})
    assert too_many.status_code == 422
    editor_list = await client.get("/api/v1/admin/orders", headers=viewer)
    assert editor_list.status_code == 403


async def test_telegram_message_cod_qr_chats_and_replay(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(settings, "media_root", tmp_path)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, title="Saree <silk>", price=700, quantity=4)
    key = "order-key-telegram"
    placed = await _place(
        client,
        product["id"],
        key=key,
        customer_name="Rina <b>A&B</b>",
        phone="01700000000",
        area="Mirpur <North>",
    )
    assert len(recorder.posts) == len(_CHATS)
    urls = {url for url, _body in recorder.posts}
    assert urls == {f"https://api.telegram.org/bot{_TOKEN}/sendMessage"}
    texts = [body["text"] for _url, body in recorder.posts]
    assert texts[0] == texts[1]
    text = texts[0]
    assert f"New order {placed['number']}" in text
    assert "Rina &lt;b&gt;A&amp;B&lt;/b&gt;" in text
    assert "<b>A&B</b>" not in text
    assert "01700000000" in text
    assert "Mirpur &lt;North&gt;" in text
    assert "Saree &lt;silk&gt; × 1" in text
    assert f"Total: ৳{placed['total']}" in text
    assert f"Cash on delivery — due ৳{placed['due_amount']}" in text
    assert f"{_BASE}/admin/orders/{placed['id']}" in text
    assert "Open order" in text
    for _url, body in recorder.posts:
        assert body["parse_mode"] == "HTML"
        assert body["disable_web_page_preview"] is True
    assert [body["chat_id"] for _url, body in recorder.posts] == _CHATS
    assert recorder.timeouts == [telegram_notify.HTTP_TIMEOUT]

    stored = await db_session.get(Order, uuid.UUID(placed["id"]))
    assert stored is not None and stored.telegram_notified_at is not None
    again = await telegram_notify.claim_new_order(db_session, stored.id)
    assert again is False

    replay = await _place(client, product["id"], key=key, customer_name="Rina <b>A&B</b>")
    assert replay["id"] == placed["id"]
    assert len(recorder.posts) == len(_CHATS)

    uploaded = await client.post(
        "/api/v1/admin/site/payment/qr",
        headers=auth_headers,
        files={"image": ("qr.jpg", JPEG, "image/jpeg")},
    )
    assert uploaded.status_code == 200, uploaded.text
    qr = await _place(
        client,
        product["id"],
        payment_method="bangla_qr",
        advance_percent=25,
        payment_reference="TXN1234",
    )
    qr_text = recorder.posts[-1][1]["text"]
    assert f"advance paid ৳{qr['advance_amount']}" in qr_text
    assert f"remaining ৳{qr['due_amount']}" in qr_text
    assert "Cash on delivery" not in qr_text
    assert len(recorder.posts) == len(_CHATS) * 2


async def test_telegram_failure_timeout_and_exception_still_place_the_order(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, chats=["111"])
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.error = httpx.TimeoutException("timed out")
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, title="Timeout Lamp", price=500, quantity=3)
    body = await _place(client, product["id"])
    assert body["number"].startswith("IM-")
    assert len(recorder.posts) == telegram_notify.MAX_ATTEMPTS
    assert logs[-1] == (
        "telegram_failed",
        {"order_number": body["number"], "error_type": "network"},
    )
    assert _TOKEN not in repr(logs)

    recorder.error = RuntimeError(f"boom {_TOKEN} secret-chat")
    logs.clear()
    recorder.posts.clear()
    body = await _place(client, product["id"])
    assert body["order_number"] == body["number"]
    assert logs[-1][0] == "telegram_failed"
    assert logs[-1][1]["order_number"] == body["number"]
    assert logs[-1][1]["error_type"] == "unexpected"
    assert _TOKEN not in repr(logs)
    assert "secret-chat" not in repr(logs)

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError(f"{_TOKEN} while building")

    monkeypatch.setattr(telegram_notify, "build_new_order_message", _boom)
    logs.clear()
    recorder.posts.clear()
    body = await _place(client, product["id"])
    assert body["number"].startswith("IM-")
    assert recorder.posts == []
    assert logs == [("telegram_schedule_failed", {"order_number": body["number"]})]
    assert _TOKEN not in repr(logs)


async def test_retries_backoff_and_retry_after(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, chats=["111"])
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.statuses = [500, 200]
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, title="Retry Lamp", price=500, quantity=5)
    await _place(client, product["id"])
    assert len(recorder.posts) == 2
    assert recorder.sleeps == [telegram_notify.BACKOFF_SECONDS[0]]
    assert logs[-1][0] == "telegram_sent"

    recorder.posts.clear()
    recorder.sleeps.clear()
    logs.clear()
    recorder.statuses = [429, 200]
    recorder.retry_after = 2
    await _place(client, product["id"])
    assert len(recorder.posts) == 2
    assert recorder.sleeps == [2]
    assert logs[-1][0] == "telegram_sent"

    recorder.posts.clear()
    recorder.sleeps.clear()
    logs.clear()
    recorder.statuses = [400]
    recorder.retry_after = None
    await _place(client, product["id"])
    assert len(recorder.posts) == 1
    assert recorder.sleeps == []
    assert logs[-1] == (
        "telegram_failed",
        {"order_number": logs[-1][1]["order_number"], "status_code": 400},
    )


async def test_empty_telegram_config_sends_nothing_and_leaves_the_order(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable(monkeypatch)
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, title="Quiet Lamp", price=500, quantity=2)
    product_url = f"/api/v1/admin/products/{product['id']}"
    before = (await client.get(product_url, headers=auth_headers)).json()
    body = await _place(client, product["id"])
    after = (await client.get(product_url, headers=auth_headers)).json()
    assert body["payment_method"] == "cod"
    assert body["due_amount"] == body["total"]
    assert after["quantity"] == before["quantity"] - 1
    assert recorder.posts == []
    assert recorder.timeouts == []
    assert logs == []
    stored = await db_session.get(Order, uuid.UUID(body["id"]))
    assert stored is not None and stored.telegram_notified_at is None

    _enable(monkeypatch, chats=[])
    await _place(client, product["id"])
    assert recorder.posts == []


async def test_optional_flags_default_off_and_fire_when_set(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert settings.telegram_notify_order_cancelled is False
    assert settings.telegram_notify_low_stock is False
    _enable(monkeypatch, chats=["111"])
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, title="Crossing Shirt", price=400, quantity=6)
    quiet = await _place(client, product["id"])
    assert len(recorder.posts) == 1
    assert "Low stock" not in recorder.posts[0][1]["text"]
    cancelled = await client.patch(
        f"/api/v1/admin/orders/{quiet['id']}",
        headers=auth_headers,
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert len(recorder.posts) == 1

    _enable(monkeypatch, chats=["111"], cancelled=True, low_stock=True)
    crossed = await _place(client, product["id"])
    low_texts = [body["text"] for _url, body in recorder.posts if "Low stock" in body["text"]]
    assert len(low_texts) == 1
    assert "Crossing Shirt" in low_texts[0]
    assert "is now 5" in low_texts[0]
    assert str(LOW_STOCK_THRESHOLD) in low_texts[0]
    # Already at the threshold: another sale must not alert again.
    again = await _place(client, product["id"])
    low_after = [body["text"] for _url, body in recorder.posts if "Low stock" in body["text"]]
    assert low_after == low_texts

    high = await _create(client, auth_headers, title="Plenty Caps", price=300, quantity=10)
    await _place(client, high["id"])
    plenty_alerts = [
        body["text"]
        for _url, body in recorder.posts
        if "Plenty Caps" in body["text"] and "Low stock" in body["text"]
    ]
    assert plenty_alerts == []

    already = await _create(client, auth_headers, title="Short Stock", price=300, quantity=4)
    await _place(client, already["id"])
    assert not any(
        "Low stock" in body["text"] and "Short Stock" in body["text"]
        for _url, body in recorder.posts
    )

    moved = await client.patch(
        f"/api/v1/admin/orders/{crossed['id']}",
        headers=auth_headers,
        json={"status": "cancelled"},
    )
    assert moved.status_code == 200, moved.text
    cancel_texts = [
        body["text"] for _url, body in recorder.posts if "Order cancelled" in body["text"]
    ]
    assert len(cancel_texts) == 1
    assert crossed["number"] in cancel_texts[0]
    assert f"{_BASE}/admin/orders/{crossed['id']}" in cancel_texts[0]
    # The second order is still new; cancelling the crossed one does not repeat it.
    assert again["number"] not in cancel_texts[0]

    adjusted = await client.post(
        "/api/v1/admin/inventory/adjustments",
        headers=auth_headers,
        json={
            "product_id": high["id"],
            "quantity": -5,
            "reason": "Count was wrong",
        },
    )
    assert adjusted.status_code == 201, adjusted.text
    assert any(
        "Low stock" in body["text"] and "Plenty Caps" in body["text"] and "is now 4" in body["text"]
        for _url, body in recorder.posts
    )
    before = len(recorder.posts)
    second_adjust = await client.post(
        "/api/v1/admin/inventory/adjustments",
        headers=auth_headers,
        json={"product_id": high["id"], "quantity": -1, "reason": "One more damaged"},
    )
    assert second_adjust.status_code == 201, second_adjust.text
    assert len(recorder.posts) == before
