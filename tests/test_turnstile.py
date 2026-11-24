"""Turnstile siteverify on public checkout. The HTTP client is mocked."""

import uuid
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import turnstile
from tests.test_products import _create

_SECRET = "test-turnstile-secret"
_TOKEN = "turnstile-token-ok"
_IP = "203.0.113.44"


def _key() -> str:
    return uuid.uuid4().hex


def _order(product_id: str, **extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "source": "direct",
        "items": [{"product_id": product_id, "quantity": 1}],
        "customer_name": "Rina Akter",
        "phone": "01700000000",
        "email": "",
        "district": "Dhaka",
        "area": "Mirpur",
        "address": "House 12, Road 4",
    }
    body.update(extra)
    return body


def _enable(
    monkeypatch: pytest.MonkeyPatch, *, secret: str = _SECRET, environment: str = "test"
) -> None:
    monkeypatch.setattr(settings, "turnstile_secret_key", secret)
    monkeypatch.setattr(settings, "environment", environment)


class _Response:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Recorder:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.timeouts: list[object] = []
        self.follow: list[object] = []
        self.status_code = 200
        self.payload: object = {"success": True}
        self.error: Exception | None = None

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = self

        class _Client:
            def __init__(self, *_args: object, **kwargs: object) -> None:
                recorder.timeouts.append(kwargs.get("timeout"))
                recorder.follow.append(kwargs.get("follow_redirects"))

            async def __aenter__(self) -> "_Client":
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def post(
                self,
                url: str,
                *,
                data: dict[str, Any] | None = None,
                json: dict[str, Any] | None = None,
            ) -> _Response:
                del json
                recorder.posts.append((url, dict(data or {})))
                if recorder.error is not None:
                    raise recorder.error
                return _Response(recorder.status_code, recorder.payload)

        monkeypatch.setattr(turnstile.httpx, "AsyncClient", _Client)


def _logs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []

    def _record(event: str, **kwargs: Any) -> None:
        found.append((event, kwargs))

    monkeypatch.setattr(turnstile.logger, "debug", _record)
    monkeypatch.setattr(turnstile.logger, "info", _record)
    monkeypatch.setattr(turnstile.logger, "warning", _record)
    monkeypatch.setattr(turnstile.logger, "error", _record)
    return found


def _assert_failed(response: httpx.Response) -> None:
    assert response.status_code == 400, response.text
    body = response.json()
    assert body == {
        "error": {
            "code": "turnstile_failed",
            "message": turnstile.FAILED_MESSAGE,
            "details": None,
        }
    }
    assert _SECRET not in response.text
    assert _TOKEN not in response.text


async def test_valid_token_places_the_order_and_replay_skips_siteverify(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, price=15000, quantity=3)

    placed = await client.post(
        "/api/v1/orders",
        headers={
            "Idempotency-Key": "turnstile-key-1",
            "CF-Connecting-IP": f"  {_IP}  ",
            "X-Forwarded-For": "198.51.100.9",
        },
        json=_order(product["id"], turnstile_token=f"  {_TOKEN}  "),
    )
    assert placed.status_code == 201, placed.text
    assert _TOKEN not in placed.text
    assert len(recorder.posts) == 1
    url, form = recorder.posts[0]
    assert url == turnstile.SITEVERIFY_URL
    assert form == {"secret": _SECRET, "response": _TOKEN, "remoteip": _IP}
    assert recorder.timeouts == [turnstile.HTTP_TIMEOUT]
    assert recorder.follow == [False]
    assert logs == []

    replay = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "turnstile-key-1"},
        json=_order(product["id"]),
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == placed.json()["id"]
    assert len(recorder.posts) == 1

    again = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=_order(product["id"], turnstile_token=_TOKEN),
    )
    assert again.status_code == 201, again.text
    assert len(recorder.posts) == 2
    assert "remoteip" not in recorder.posts[1][1]


async def test_rejected_and_unreachable_siteverify_are_400(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.payload = {"success": False, "error-codes": ["invalid-input-response"]}
    recorder.install(monkeypatch)
    product_id = str(uuid.uuid4())

    rejected = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key(), "CF-Connecting-IP": _IP},
        json=_order(product_id, turnstile_token=_TOKEN),
    )
    _assert_failed(rejected)
    assert len(recorder.posts) == 1
    assert logs == [("turnstile_rejected", {})]
    assert _SECRET not in repr(logs)
    assert _TOKEN not in repr(logs)

    logs.clear()
    recorder.payload = {"success": True}
    recorder.status_code = 500
    server = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=_order(product_id, turnstile_token=_TOKEN),
    )
    _assert_failed(server)

    logs.clear()
    recorder.error = httpx.TimeoutException(f"timed out {_SECRET} {_TOKEN}")
    timed = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=_order(product_id, turnstile_token=_TOKEN),
    )
    _assert_failed(timed)
    assert logs == [("turnstile_siteverify_failed", {"error_type": "network"})]
    assert _SECRET not in repr(logs)
    assert _TOKEN not in repr(logs)
    assert "timed out" not in repr(logs)


async def test_missing_token_is_400_and_the_header_is_not_accepted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product_id = str(uuid.uuid4())

    missing = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=_order(product_id),
    )
    _assert_failed(missing)

    blank = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=_order(product_id, turnstile_token="   "),
    )
    _assert_failed(blank)

    header_only = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key(), "X-Turnstile-Token": _TOKEN},
        json=_order(product_id),
    )
    _assert_failed(header_only)
    assert recorder.posts == []


async def test_unset_secret_skips_verification_outside_production(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, secret="   ", environment="local")
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, price=15000, quantity=2)
    placed = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=_order(product["id"]),
    )
    assert placed.status_code == 201, placed.text
    assert recorder.posts == []
    assert logs == [
        (
            "turnstile_skipped",
            {"detail": "TURNSTILE_SECRET_KEY is unset; skipping verification outside production"},
        )
    ]


async def test_production_without_the_secret_fails_closed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, secret="", environment="production")
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product_id = str(uuid.uuid4())
    key = _key()
    refused = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": key},
        json=_order(product_id, turnstile_token=_TOKEN),
    )
    _assert_failed(refused)
    assert recorder.posts == []
    assert logs == [
        (
            "turnstile_not_configured",
            {
                "detail": (
                    "TURNSTILE_SECRET_KEY is unset; refusing public checkout in production"
                )
            },
        )
    ]
    assert _TOKEN not in repr(logs)

    logs.clear()
    monkeypatch.setattr(settings, "turnstile_secret_key", "   ")
    again = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": key},
        json=_order(product_id),
    )
    _assert_failed(again)
    assert recorder.posts == []
    assert logs[0][0] == "turnstile_not_configured"


async def test_admin_and_offline_do_not_require_a_token(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, environment="production")
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, price=900, quantity=4)

    quoted = await client.post(
        "/api/v1/orders/quote",
        json={
            "source": "direct",
            "items": [{"product_id": str(uuid.uuid4()), "quantity": 1}],
            "district": "Dhaka",
            "area": "Mirpur",
        },
    )
    assert quoted.status_code == 404
    assert quoted.json()["error"]["code"] != "turnstile_failed"

    lookup = await client.post(
        "/api/v1/orders/lookup",
        json={"number": "IM-ABCDEF01", "phone": "01700000000"},
    )
    assert lookup.status_code == 404
    assert lookup.json()["error"]["code"] != "turnstile_failed"

    offline = await client.post(
        "/api/v1/admin/orders/offline",
        headers={**auth_headers, "Idempotency-Key": _key()},
        json={
            "customer_name": "Karim Uddin",
            "phone": "01800000000",
            "email": "",
            "district": "Dhaka",
            "area": "Gulshan",
            "address": "House 4, Road 12, Gulshan",
            "notes": "Counter sale",
            "items": [{"product_id": product["id"], "quantity": 1, "unit_price": 500}],
            "manual_discount": 0,
            "delivery_charge": 80,
            "payment_method": "cash",
            "paid_amount": 200,
        },
    )
    assert offline.status_code == 201, offline.text
    updated = await client.patch(
        f"/api/v1/admin/orders/{offline.json()['id']}",
        headers=auth_headers,
        json={"status": "confirmed"},
    )
    assert updated.status_code == 200, updated.text
    assert recorder.posts == []
