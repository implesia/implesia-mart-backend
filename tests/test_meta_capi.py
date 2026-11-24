"""Meta Conversions API Purchase events. The HTTP client is mocked; nothing is sent."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr, ValidationError
from starlette.background import BackgroundTasks
from starlette.requests import Request

from app.core.config import settings
from app.models.order import Order, OrderItem
from app.schemas.order import OrderCreate, OrderTracking
from app.services import meta_capi
from tests.test_products import _create

_PIXEL = "1234567890"
_TOKEN = "test-capi-token"
_TEST_CODE = "TEST12345"
_EMAIL = "Owner@Example.com"
_PHONE_RAW = "+880 1700-000000"
_PHONE_INTL = "8801700000000"
_FBP = "fb.1.1700000000.abc"
_FBC = "fb.1.1700000000.def"
_SOURCE_URL = "https://shop.example/checkout"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _enable(monkeypatch: pytest.MonkeyPatch, *, test_code: str = "") -> None:
    monkeypatch.setattr(settings, "meta_pixel_id", _PIXEL)
    monkeypatch.setattr(settings, "meta_capi_token", SecretStr(_TOKEN))
    monkeypatch.setattr(settings, "meta_test_event_code", test_code)


def _disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "meta_pixel_id", "")
    monkeypatch.setattr(settings, "meta_capi_token", SecretStr(""))
    monkeypatch.setattr(settings, "meta_test_event_code", "")


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _Recorder:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.statuses: list[int] = []
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

            async def post(
                self,
                url: str,
                *,
                params: dict[str, Any] | None = None,
                json: dict[str, Any] | None = None,
            ) -> _Response:
                recorder.posts.append((url, params or {}, json or {}))
                if recorder.error is not None:
                    raise recorder.error
                status = recorder.statuses.pop(0) if recorder.statuses else 200
                return _Response(status)

        monkeypatch.setattr(meta_capi.httpx, "AsyncClient", _Client)

        async def _sleep(_delay: float) -> None:
            return None

        monkeypatch.setattr(meta_capi.asyncio, "sleep", _sleep)


def _logs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []

    def _record(event: str, **kwargs: Any) -> None:
        found.append((event, kwargs))

    monkeypatch.setattr(meta_capi.logger, "error", _record)
    monkeypatch.setattr(meta_capi.logger, "info", _record)
    return found


def _direct(**extra: object) -> dict[str, object]:
    body: dict[str, object] = {
        "source": "direct",
        "items": [{"product_id": str(uuid.uuid4()), "quantity": 1}],
        "customer_name": "Rina Akter",
        "phone": "01700000000",
        "email": "",
        "district": "Dhaka",
        "area": "Mirpur",
        "address": "House 12, Road 4",
    }
    body.update(extra)
    return body


def _sample_order() -> Order:
    product_a = uuid.uuid4()
    product_b = uuid.uuid4()
    when = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    order = Order(
        number="IM-ABCDEF01",
        source="direct",
        status="new",
        customer_name="Rina Akter",
        phone="01712345678",
        email="  Owner@Example.com ",
        district="Dhaka",
        area="Mirpur",
        address="House 12, Road 4, Mirpur",
        notes="leave at the door",
        delivery_zone="inside",
        subtotal=250,
        shipping=70,
        total=320,
        created_at=when,
    )
    order.items = [
        OrderItem(
            product_id=product_a,
            title="Saree",
            slug="saree",
            unit_price=100,
            quantity=2,
            line_total=200,
        ),
        OrderItem(
            product_id=None,
            title="Deleted",
            slug="deleted",
            unit_price=9,
            quantity=4,
            line_total=36,
        ),
        OrderItem(
            product_id=product_b,
            title="Blouse",
            slug="blouse",
            unit_price=50,
            quantity=1,
            line_total=50,
        ),
    ]
    return order


def test_email_and_phone_hashes() -> None:
    assert meta_capi.hash_email("  Owner@Example.com ") == _sha("owner@example.com")
    assert meta_capi.hash_email("   ") is None
    assert meta_capi.hash_email("") is None

    expected = _sha("8801712345678")
    assert meta_capi.hash_phone("01712345678") == expected
    assert meta_capi.hash_phone("01712 345 678") == expected
    assert meta_capi.hash_phone("+8801712345678") == expected
    assert meta_capi.hash_phone("+880 1712-345678") == expected
    assert meta_capi.hash_phone("8801712345678") == expected
    assert meta_capi.hash_phone("8801 712-345678") == expected
    assert meta_capi.normalize_phone("01712345678") == "8801712345678"
    assert meta_capi.normalize_phone("8801712345678") == "8801712345678"
    assert meta_capi.hash_phone(_PHONE_RAW) == _sha(_PHONE_INTL)

    assert meta_capi.hash_phone("12345") is None
    assert meta_capi.hash_phone("0171234567") is None
    assert meta_capi.hash_phone("880171234567") is None
    assert meta_capi.hash_phone("not-a-phone") is None
    assert meta_capi.hash_phone("") is None
    assert meta_capi.hash_phone(_PHONE_INTL) != _sha("01712345678")


def test_location_name_and_external_id_normalization() -> None:
    assert meta_capi.normalize_location("  Dhaka. ") == "dhaka"
    assert meta_capi.normalize_location("New York") == "newyork"
    assert meta_capi.normalize_location("Cox's Bazar") == "coxsbazar"
    assert meta_capi.normalize_location("  BD ") == "bd"
    assert meta_capi.normalize_location("ঢাকা") == "ঢাকা"
    assert meta_capi.normalize_location("   ") is None
    assert meta_capi.normalize_location("...") is None
    assert meta_capi.hash_location("Dhaka") == _sha("dhaka")
    assert meta_capi.hash_location("...") is None

    assert meta_capi.name_parts("  Rina   Akter ") == ("rina", "akter")
    assert meta_capi.name_parts("Mary-Jane Watson") == ("maryjane", "watson")
    assert meta_capi.name_parts("Md. Rina Akter") == ("md", "akter")
    assert meta_capi.name_parts("Rina") == ("rina", None)
    assert meta_capi.name_parts("O'Brien") == ("obrien", None)
    assert meta_capi.name_parts("রিনা আক্তার") == ("রিনা", "আক্তার")
    assert meta_capi.name_parts("...") == (None, None)
    assert meta_capi.hash_external_id("  AbC-1 ") == _sha("abc-1")
    assert meta_capi.hash_external_id("   ") is None


def _request(peer: str | None, headers: dict[str, str]) -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    client = None if peer is None else (peer, 50000)
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": raw,
            "client": client,
            "server": ("testserver", 80),
        }
    )


def test_client_ip_header_priority() -> None:
    cloudflare = _request(
        "10.0.0.5",
        {
            "CF-Connecting-IP": " 203.0.113.10 ",
            "X-Forwarded-For": "198.51.100.8, 10.0.0.5",
        },
    )
    assert meta_capi.client_ip_address(cloudflare) == "203.0.113.10"

    forwarded = _request("10.0.0.5", {"X-Forwarded-For": "  198.51.100.1 , 10.0.0.5"})
    assert meta_capi.client_ip_address(forwarded) == "198.51.100.1"

    blank = _request("203.0.113.8", {"CF-Connecting-IP": "   ", "X-Forwarded-For": " , "})
    assert meta_capi.client_ip_address(blank) == "203.0.113.8"

    direct = _request("203.0.113.8", {})
    assert meta_capi.client_ip_address(direct) == "203.0.113.8"
    assert meta_capi.client_ip_address(_request(None, {})) is None
    assert meta_capi.client_user_agent(direct) is None
    with_agent = _request("127.0.0.1", {"User-Agent": "  MartBrowser/1.0  "})
    assert meta_capi.client_user_agent(with_agent) == "MartBrowser/1.0"


def test_purchase_body_fields_and_no_extra_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, test_code=_TEST_CODE)
    order = _sample_order()
    kept = [item for item in order.items if item.product_id is not None]
    tracking = OrderTracking(fbp=_FBP, fbc=_FBC, event_source_url=_SOURCE_URL)
    body = meta_capi.build_purchase_body(
        order,
        tracking,
        client_ip=" 203.0.113.10 ",
        user_agent=" MartBrowser/1.0 ",
    )

    assert set(body) == {"data", "test_event_code"}
    assert body["test_event_code"] == _TEST_CODE
    event = body["data"][0]
    assert set(event) == {
        "event_name",
        "event_time",
        "event_id",
        "action_source",
        "event_source_url",
        "custom_data",
        "user_data",
    }
    assert event["event_name"] == "Purchase"
    assert event["event_time"] == int(datetime(2026, 11, 10, 12, 0, tzinfo=UTC).timestamp())
    assert event["event_id"] == "purchase_IM-ABCDEF01"
    assert event["action_source"] == "website"
    assert event["event_source_url"] == _SOURCE_URL

    custom = event["custom_data"]
    assert custom["value"] == 320
    assert isinstance(custom["value"], int)
    assert custom["currency"] == "BDT"
    assert custom["content_type"] == "product"
    assert custom["content_ids"] == [str(item.product_id) for item in kept]
    assert custom["num_items"] == 3
    assert custom["order_id"] == "IM-ABCDEF01"
    assert custom["contents"] == [
        {"id": str(item.product_id), "quantity": item.quantity, "item_price": item.unit_price}
        for item in kept
    ]
    for row in custom["contents"]:
        assert set(row) == {"id", "quantity", "item_price"}

    user_data = event["user_data"]
    assert set(user_data) == {
        "ph",
        "em",
        "fn",
        "ln",
        "ct",
        "country",
        "external_id",
        "client_ip_address",
        "client_user_agent",
        "fbp",
        "fbc",
    }
    assert user_data["ph"] == [_sha("8801712345678")]
    assert user_data["em"] == [_sha("owner@example.com")]
    assert user_data["fn"] == [_sha("rina")]
    assert user_data["ln"] == [_sha("akter")]
    assert user_data["ct"] == [_sha("dhaka")]
    assert user_data["country"] == [_sha("bd")]
    assert user_data["external_id"] == [_sha("8801712345678")]
    assert user_data["client_ip_address"] == "203.0.113.10"
    assert user_data["client_user_agent"] == "MartBrowser/1.0"
    assert user_data["fbp"] == _FBP
    assert user_data["fbc"] == _FBC

    dumped = str(body)
    for secret in (
        "Rina Akter",
        "House 12",
        "Mirpur",
        "Dhaka",
        "leave at the door",
        "01712345678",
        "Owner@Example.com",
        "owner@example.com",
        _TOKEN,
    ):
        assert secret not in dumped

    bare = meta_capi.build_purchase_body(order, None)
    assert "test_event_code" in bare
    assert set(bare["data"][0]["user_data"]) == {
        "ph",
        "em",
        "fn",
        "ln",
        "ct",
        "country",
        "external_id",
    }
    assert "event_source_url" not in bare["data"][0]
    assert "fbp" not in bare["data"][0]["user_data"]
    assert "client_ip_address" not in bare["data"][0]["user_data"]

    monkeypatch.setattr(settings, "meta_test_event_code", "  ")
    quiet = meta_capi.build_purchase_body(order, OrderTracking())
    assert "test_event_code" not in quiet
    order.email = ""
    order.phone = "12345"
    order.customer_name = "..."
    order.district = "..."
    omitted = meta_capi.build_purchase_body(order, None)
    assert set(omitted["data"][0]["user_data"]) == {"country"}
    assert omitted["data"][0]["user_data"]["country"] == [_sha("bd")]

    customer_id = uuid.uuid4()
    identified = _sample_order()
    identified.user_id = customer_id
    identified_body = meta_capi.build_purchase_body(identified, None)
    identified_user = identified_body["data"][0]["user_data"]
    assert identified_user["external_id"] == [_sha(str(customer_id))]
    assert identified_user["external_id"] != identified_user["ph"]
    assert str(customer_id) not in str(identified_body)


def test_offline_origin_is_not_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, test_code=_TEST_CODE)
    order = _sample_order()
    order.origin = "offline"
    offline = BackgroundTasks()
    meta_capi.schedule_purchase(offline, order, OrderTracking(fbp=_FBP, fbc=_FBC))
    assert offline.tasks == []

    order.origin = "online"
    online = BackgroundTasks()
    meta_capi.schedule_purchase(online, order, None, client_ip="203.0.113.10", user_agent="UA")
    assert len(online.tasks) == 1


def test_blank_settings_disable_capi(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    assert meta_capi.enabled() is True
    monkeypatch.setattr(settings, "meta_pixel_id", "   ")
    assert meta_capi.enabled() is False
    monkeypatch.setattr(settings, "meta_pixel_id", _PIXEL)
    monkeypatch.setattr(settings, "meta_capi_token", SecretStr("  "))
    assert meta_capi.enabled() is False


def test_tracking_is_optional_and_invalid_values_are_ignored() -> None:
    created = OrderCreate.model_validate(_direct())
    assert created.tracking is None

    created = OrderCreate.model_validate(_direct(tracking=None))
    assert created.tracking is None

    created = OrderCreate.model_validate(_direct(tracking="nope"))
    assert created.tracking is None

    created = OrderCreate.model_validate(
        _direct(
            tracking={
                "fbp": "  fb.1.1.ok  ",
                "fbc": None,
                "event_source_url": 12,
                "extra": "ignored",
            }
        )
    )
    assert created.tracking is not None
    assert created.tracking.fbp == "fb.1.1.ok"
    assert created.tracking.fbc is None
    assert created.tracking.event_source_url is None

    created = OrderCreate.model_validate(_direct(tracking={"fbp": "x" * 501, "fbc": "y" * 500}))
    assert created.tracking is not None
    assert created.tracking.fbp is None
    assert created.tracking.fbc == "y" * 500

    with pytest.raises(ValidationError):
        OrderCreate.model_validate(_direct(not_a_field=1))


async def test_send_retries_timeouts_and_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, test_code=_TEST_CODE)
    logs = _logs(monkeypatch)
    slept: list[float] = []

    async def _sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(meta_capi.asyncio, "sleep", _sleep)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    # install() replaces sleep; put the recording sleep back.
    monkeypatch.setattr(meta_capi.asyncio, "sleep", _sleep)

    body = {"data": [{"event_id": "purchase_IM-ABCDEF01"}]}
    recorder.statuses = [500, 429, 200]
    await meta_capi.send_purchase("IM-ABCDEF01", body)
    assert len(recorder.posts) == 3
    assert slept == [0.5, 1.0]
    url, params, posted = recorder.posts[0]
    assert url == f"https://graph.facebook.com/v21.0/{_PIXEL}/events"
    assert params == {"access_token": _TOKEN}
    assert posted == body
    assert _TOKEN not in str(posted)
    assert recorder.timeouts == [meta_capi.HTTP_TIMEOUT]
    assert logs[-1] == ("meta_capi_purchase_sent", {"order_number": "IM-ABCDEF01"})

    logs.clear()
    slept.clear()
    recorder.posts.clear()
    recorder.statuses = [400]
    await meta_capi.send_purchase("IM-ABCDEF01", body)
    assert len(recorder.posts) == 1
    assert slept == []
    assert logs == [
        ("meta_capi_purchase_failed", {"order_number": "IM-ABCDEF01", "status_code": 400})
    ]

    logs.clear()
    recorder.posts.clear()
    recorder.statuses = []
    recorder.error = httpx.TimeoutException("timed out")
    await meta_capi.send_purchase("IM-ABCDEF01", body)
    assert len(recorder.posts) == 3
    assert logs == [
        ("meta_capi_purchase_failed", {"order_number": "IM-ABCDEF01", "error_type": "network"})
    ]
    assert _TOKEN not in repr(logs)
    assert "timed out" not in repr(logs)

    logs.clear()
    recorder.posts.clear()
    recorder.error = RuntimeError(f"{_TOKEN} 01712345678 owner@example.com")
    await meta_capi.send_purchase("IM-ABCDEF01", body)
    assert len(recorder.posts) == 1
    assert logs == [
        ("meta_capi_purchase_failed", {"order_number": "IM-ABCDEF01", "error_type": "unexpected"})
    ]
    assert _TOKEN not in repr(logs)
    assert "01712345678" not in repr(logs)
    assert "owner@example.com" not in repr(logs)


async def test_send_is_skipped_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _disable(monkeypatch)
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    await meta_capi.send_purchase("IM-ABCDEF01", {"data": []})
    assert recorder.posts == []
    assert recorder.timeouts == []
    assert logs == []


def _key() -> str:
    return uuid.uuid4().hex


async def _place(
    client: AsyncClient,
    product_id: str,
    *,
    tracking: object | None = None,
    email: str = "",
    phone: str = "01700000000",
) -> dict[str, Any]:
    payload: dict[str, object] = {
        "source": "direct",
        "items": [{"product_id": product_id, "quantity": 1}],
        "customer_name": "Rina Akter",
        "phone": phone,
        "email": email,
        "district": "ঢাকা",
        "area": "মিরপুর",
        "address": "House 12, Road 4, Mirpur",
        "notes": "",
    }
    if tracking is not None:
        payload["tracking"] = tracking
    response = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json=payload,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_order_create_sends_one_purchase_matching_the_response(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, test_code=_TEST_CODE)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, price=15000, quantity=4)

    placed = await client.post(
        "/api/v1/orders",
        headers={
            "Idempotency-Key": "order-key-1",
            "CF-Connecting-IP": "203.0.113.10",
            "X-Forwarded-For": "198.51.100.8, 203.0.113.10",
            "User-Agent": "MartBrowser/1.0",
        },
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 1}],
            "customer_name": "Rina Akter",
            "phone": _PHONE_RAW,
            "email": _EMAIL,
            "district": "ঢাকা",
            "area": "মিরপুর",
            "address": "House 12, Road 4, Mirpur",
            "notes": "ring the bell",
            "tracking": {"fbp": _FBP, "fbc": _FBC, "event_source_url": _SOURCE_URL},
        },
    )
    assert placed.status_code == 201, placed.text
    body = placed.json()
    assert body["number"].startswith("IM-")
    assert body["order_number"] == body["number"]
    assert body["analytics_event_id"] == f"purchase_{body['order_number']}"
    assert len(recorder.posts) == 1

    _url, params, posted = recorder.posts[0]
    assert params["access_token"] == _TOKEN
    event = posted["data"][0]
    assert event["event_id"] == body["analytics_event_id"]
    assert isinstance(event["event_time"], int)
    assert abs(event["event_time"] - int(datetime.now(UTC).timestamp())) < 120
    assert event["custom_data"]["value"] == body["total"]
    assert event["custom_data"]["currency"] == "BDT"
    assert event["custom_data"]["order_id"] == body["order_number"]
    assert event["custom_data"]["content_ids"] == [body["items"][0]["product_id"]]
    assert event["custom_data"]["contents"] == [
        {
            "id": body["items"][0]["product_id"],
            "quantity": body["items"][0]["quantity"],
            "item_price": body["items"][0]["unit_price"],
        }
    ]
    assert event["custom_data"]["num_items"] == 1
    assert event["user_data"]["ph"] == [_sha(_PHONE_INTL)]
    assert event["user_data"]["em"] == [_sha(_EMAIL.lower())]
    assert event["user_data"]["fn"] == [_sha("rina")]
    assert event["user_data"]["ln"] == [_sha("akter")]
    assert event["user_data"]["ct"] == [_sha("ঢাকা")]
    assert event["user_data"]["country"] == [_sha("bd")]
    assert event["user_data"]["external_id"] == [_sha(_PHONE_INTL)]
    assert event["user_data"]["client_ip_address"] == "203.0.113.10"
    assert event["user_data"]["client_user_agent"] == "MartBrowser/1.0"
    assert event["user_data"]["fbp"] == _FBP
    assert event["user_data"]["fbc"] == _FBC
    assert event["event_source_url"] == _SOURCE_URL
    assert posted["test_event_code"] == _TEST_CODE
    dumped = str(posted)
    for secret in (
        "Rina Akter",
        "House 12",
        "ring the bell",
        "01700000000",
        "ঢাকা",
        _PHONE_RAW,
        _PHONE_INTL,
        _EMAIL,
        _EMAIL.lower(),
        _TOKEN,
    ):
        assert secret not in dumped

    replay = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": "order-key-1"},
        json={
            "source": "direct",
            "items": [{"product_id": product["id"], "quantity": 1}],
            "customer_name": "Rina Akter",
            "phone": "01700000000",
            "email": _EMAIL,
            "district": "ঢাকা",
            "area": "মিরপুর",
            "address": "House 12, Road 4, Mirpur",
        },
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["analytics_event_id"] == body["analytics_event_id"]
    assert len(recorder.posts) == 1

    updated = await client.patch(
        f"/api/v1/admin/orders/{body['id']}",
        headers=auth_headers,
        json={"status": "confirmed"},
    )
    assert updated.status_code == 200, updated.text
    assert len(recorder.posts) == 1

    second = await _place(client, product["id"], email="")
    assert second["analytics_event_id"] == f"purchase_{second['order_number']}"
    assert second["analytics_event_id"] != body["analytics_event_id"]
    assert len(recorder.posts) == 2
    assert "em" not in recorder.posts[1][2]["data"][0]["user_data"]


async def test_capi_failure_still_places_the_order(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.error = httpx.TimeoutException("timed out")
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, price=15000, quantity=2)
    body = await _place(client, product["id"], email=_EMAIL, phone="01800000000")
    assert body["analytics_event_id"] == f"purchase_{body['order_number']}"
    assert len(recorder.posts) == meta_capi.MAX_ATTEMPTS
    assert logs[-1][0] == "meta_capi_purchase_failed"
    assert logs[-1][1]["order_number"] == body["order_number"]
    blob = repr(logs)
    assert _TOKEN not in blob
    assert _EMAIL not in blob
    assert "01800000000" not in blob
    assert "8801800000000" not in blob


async def test_capi_build_error_still_places_the_order(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.install(monkeypatch)

    def _boom(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise RuntimeError(f"{_TOKEN} 01900000000 secret@example.com")

    monkeypatch.setattr(meta_capi, "build_purchase_body", _boom)
    product = await _create(client, auth_headers, price=15000, quantity=2)
    body = await _place(client, product["id"])
    assert body["order_number"] == body["number"]
    assert body["analytics_event_id"] == f"purchase_{body['number']}"
    assert recorder.posts == []
    assert logs == [("meta_capi_schedule_failed", {"order_number": body["order_number"]})]
    assert _TOKEN not in repr(logs)
    assert "secret@example.com" not in repr(logs)


async def test_disabled_capi_still_returns_the_event_id(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _disable(monkeypatch)
    logs = _logs(monkeypatch)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, price=15000, quantity=2)
    body = await _place(client, product["id"])
    assert body["analytics_event_id"] == f"purchase_{body['order_number']}"
    assert recorder.posts == []
    assert logs == []

    rejected = await client.post(
        "/api/v1/orders",
        headers={"Idempotency-Key": _key()},
        json={"source": "direct", "items": [], "tracking": {"fbp": _FBP}},
    )
    assert rejected.status_code == 422


async def test_offline_order_does_not_send_capi(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, test_code=_TEST_CODE)
    recorder = _Recorder()
    recorder.install(monkeypatch)
    product = await _create(client, auth_headers, price=900, quantity=5)
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
    assert offline.json()["origin"] == "offline"
    assert recorder.posts == []

    updated = await client.patch(
        f"/api/v1/admin/orders/{offline.json()['id']}",
        headers=auth_headers,
        json={"status": "confirmed"},
    )
    assert updated.status_code == 200, updated.text
    assert recorder.posts == []
