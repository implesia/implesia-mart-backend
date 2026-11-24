"""Customer phone report and courier fraud-check adapters."""

import importlib.util
import inspect
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.courier_check import CourierCheckResult
from app.models.order import Order
from app.models.role_permission import RolePermission
from app.models.user import User, UserRole
from app.services import permission_service
from app.services.courier.adapters import (
    GenericProvider,
    PathaoProvider,
    RedxProvider,
    SteadfastProvider,
)
from app.services.courier.service import risk_level

REPORT = "/api/v1/admin/customers/report"
REFRESH = "/api/v1/admin/customers/report/courier-check"
PHONE = "01755550101"
OTHER = "01955550199"
ADAPTER_PHONE = "01712345678"


def _order(
    phone: str,
    *,
    number: str,
    status: str,
    origin: str,
    total: int,
    created_at: datetime,
    tracking: str = "",
    user_id: object = None,
) -> Order:
    return Order(
        number=number,
        source="direct",
        origin=origin,
        status=status,
        customer_name="Buyer",
        phone=phone,
        district="Dhaka",
        area="Dhanmondi",
        address="House 1",
        delivery_zone="inside",
        payment_method="cod",
        subtotal=total,
        shipping=0,
        total=total,
        tracking_number=tracking,
        created_at=created_at,
        user_id=user_id,
    )


async def _staff(
    client: AsyncClient,
    db: AsyncSession,
    *,
    email: str,
    role: UserRole,
) -> dict[str, str]:
    password = "staff-passphrase-1234"
    db.add(
        User(
            email=email,
            full_name=f"{role.value.title()} User",
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
    )
    await db.commit()
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _http(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2)


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


def _boom(timeout: float) -> httpx.AsyncClient:
    del timeout
    raise AssertionError("courier network call")


async def test_report_aggregates_server_totals_and_normalizes_phone(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    registered = await client.post(
        "/api/v1/customer/auth/register",
        json={
            "full_name": "Amina Khatun",
            "phone": "+880 1755-550101",
            "email": "Amina@Example.com",
            "password": "customer-password-123",
        },
    )
    assert registered.status_code == 201, registered.text
    user = await db_session.scalar(select(User).where(User.phone == PHONE))
    assert user is not None
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        ("IM-RPT-1", "delivered", "online", 1500, 0, "TRK-OLD"),
        ("IM-RPT-2", "delivered", "offline", 500, 1, ""),
        ("IM-RPT-3", "cancelled", "online", 9000, 2, ""),
        ("IM-RPT-4", "returned", "offline", 700, 3, ""),
        ("IM-RPT-5", "new", "online", 100, 4, ""),
        ("IM-RPT-6", "confirmed", "online", 200, 5, ""),
        ("IM-RPT-7", "packed", "offline", 300, 6, ""),
        ("IM-RPT-8", "shipped", "online", 400, 7, "TRK-NEW"),
    ]
    for number, status, origin, total, day, tracking in rows:
        db_session.add(
            _order(
                PHONE,
                number=number,
                status=status,
                origin=origin,
                total=total,
                created_at=start + timedelta(days=day),
                tracking=tracking,
                user_id=user.id,
            )
        )
    db_session.add(
        _order(
            OTHER,
            number="IM-RPT-OTHER",
            status="delivered",
            origin="online",
            total=99999,
            created_at=start + timedelta(days=9),
            user_id=user.id,
        )
    )
    await db_session.commit()

    response = await client.get(
        REPORT,
        headers=auth_headers,
        params={"phone": "8801755550101", "total": "1"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"phone", "customer", "summary", "orders", "courier_check"}
    assert body["phone"] == PHONE
    assert set(body["customer"]) == {"id", "name", "email"}
    assert body["customer"]["name"] == "Amina Khatun"
    assert body["customer"]["email"] == "amina@example.com"
    summary = body["summary"]
    assert summary["total_orders"] == 8
    assert summary["by_status"] == {
        "new": 1,
        "confirmed": 1,
        "packed": 1,
        "shipped": 1,
        "delivered": 2,
        "cancelled": 1,
        "returned": 1,
    }
    assert summary["delivered_count"] == 2
    assert summary["cancelled_count"] == 1
    assert summary["returned_count"] == 1
    assert summary["success_rate"] == 0.5
    assert summary["total_spent"] == 2000
    assert summary["online_count"] == 5
    assert summary["offline_count"] == 3
    assert summary["first_order_at"].startswith("2026-01-01")
    assert summary["last_order_at"].startswith("2026-01-08")
    assert [row["number"] for row in body["orders"]] == [
        "IM-RPT-8",
        "IM-RPT-7",
        "IM-RPT-6",
        "IM-RPT-5",
        "IM-RPT-4",
        "IM-RPT-3",
        "IM-RPT-2",
        "IM-RPT-1",
    ]
    newest = body["orders"][0]
    assert set(newest) == {
        "id",
        "number",
        "status",
        "origin",
        "total",
        "created_at",
        "tracking_number",
    }
    assert newest["status"] == "shipped"
    assert newest["origin"] == "online"
    assert newest["total"] == 400
    assert newest["tracking_number"] == "TRK-NEW"
    assert body["orders"][1]["origin"] == "offline"


@pytest.mark.parametrize(
    "raw",
    ["01755550101", "+8801755550101", "+880 1755-550101", "০১৭৫৫৫৫০১০১"],
)
async def test_report_accepts_bd_phone_spellings(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    raw: str,
) -> None:
    db_session.add(
        _order(
            PHONE,
            number="IM-PH-1",
            status="new",
            origin="online",
            total=10,
            created_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
    )
    await db_session.commit()
    response = await client.get(REPORT, headers=auth_headers, params={"phone": raw})
    assert response.status_code == 200, response.text
    assert response.json()["phone"] == PHONE
    assert response.json()["summary"]["total_orders"] == 1


@pytest.mark.parametrize("raw", ["01112345678", "12345", "01012345678", "hello"])
async def test_report_rejects_invalid_phone(
    client: AsyncClient, auth_headers: dict[str, str], raw: str
) -> None:
    response = await client.get(REPORT, headers=auth_headers, params={"phone": raw})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_report_limits_orders_to_newest_50(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    phone = "01855550101"
    start = datetime(2026, 3, 1, tzinfo=UTC)
    for index in range(51):
        db_session.add(
            _order(
                phone,
                number=f"IM-LIM-{index:02d}",
                status="delivered",
                origin="online",
                total=10,
                created_at=start + timedelta(minutes=index),
            )
        )
    await db_session.commit()
    response = await client.get(REPORT, headers=auth_headers, params={"phone": phone})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["customer"] is None
    assert body["summary"]["total_orders"] == 51
    assert body["summary"]["total_spent"] == 510
    assert body["summary"]["success_rate"] == 1.0
    assert len(body["orders"]) == 50
    assert body["orders"][0]["number"] == "IM-LIM-50"
    assert body["orders"][-1]["number"] == "IM-LIM-01"
    assert "IM-LIM-00" not in {row["number"] for row in body["orders"]}


async def test_report_permission_follows_orders_read(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    viewer = await _staff(
        client, db_session, email="report-viewer@implesia.com", role=UserRole.VIEWER
    )
    editor = await _staff(
        client, db_session, email="report-editor@implesia.com", role=UserRole.EDITOR
    )
    registered = await client.post(
        "/api/v1/customer/auth/register",
        json={
            "full_name": "Shopper",
            "phone": "01655550199",
            "password": "customer-password-123",
        },
    )
    assert registered.status_code == 201, registered.text
    customer = {"Authorization": f"Bearer {registered.json()['access_token']}"}
    phone = {"phone": "01700000999"}

    anonymous = await client.get(REPORT, params=phone)
    assert anonymous.status_code == 401
    viewer_report = await client.get(REPORT, headers=viewer, params=phone)
    assert viewer_report.status_code == 200, viewer_report.text
    assert viewer_report.json()["summary"]["success_rate"] is None
    assert viewer_report.json()["summary"]["total_spent"] == 0
    assert (await client.get(REPORT, headers=editor, params=phone)).status_code == 200
    forbidden = await client.get(REPORT, headers=customer, params=phone)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"
    posted = await client.post(REFRESH, headers=viewer, params=phone)
    assert posted.status_code == 200
    customer_post = await client.post(REFRESH, headers=customer, params=phone)
    assert customer_post.status_code == 403

    db_session.add(RolePermission(role="viewer", module_key="orders", access_level="none"))
    await db_session.commit()
    permission_service.invalidate_permission_cache()
    denied = await client.get(REPORT, headers=viewer, params=phone)
    assert denied.status_code == 403
    assert (await client.get(REPORT, headers=editor, params=phone)).status_code == 200


async def test_courier_check_is_not_configured_without_env_and_never_calls(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.courier.service.open_client", _boom)
    params = {"phone": ADAPTER_PHONE}
    report = await client.get(REPORT, headers=auth_headers, params=params)
    assert report.status_code == 200, report.text
    check = report.json()["courier_check"]
    assert set(check) == {
        "enabled",
        "checked_at",
        "stale",
        "totals",
        "risk_level",
        "providers",
    }
    assert check["enabled"] is False
    assert check["checked_at"] is None
    assert check["stale"] is False
    assert check["risk_level"] == "unknown"
    assert check["totals"] == {
        "total_parcels": 0,
        "delivered": 0,
        "returned_or_cancelled": 0,
        "success_rate": None,
    }
    assert [row["provider"] for row in check["providers"]] == [
        "steadfast",
        "pathao",
        "redx",
        "generic",
    ]
    assert {row["status"] for row in check["providers"]} == {"not_configured"}

    monkeypatch.setattr(settings, "steadfast_api_key", SecretStr("test-steadfast-key"))
    monkeypatch.setattr(settings, "steadfast_secret_key", SecretStr("test-steadfast-secret"))
    held = await client.post(REFRESH, headers=auth_headers, params=params)
    assert held.status_code == 200, held.text
    assert held.json()["enabled"] is False
    steadfast = next(row for row in held.json()["providers"] if row["provider"] == "steadfast")
    assert steadfast["status"] == "error"
    assert steadfast["error_message"] == "No cached result"


def test_risk_level_uses_ratio_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "courier_check_risk_high_below", 0.5)
    monkeypatch.setattr(settings, "courier_check_risk_medium_below", 0.8)
    assert risk_level(None) == "unknown"
    assert risk_level(0.49) == "high"
    assert risk_level(0.5) == "medium"
    assert risk_level(0.79) == "medium"
    assert risk_level(0.8) == "low"


async def test_courier_cache_staleness_and_cached_get_does_not_call(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "courier_check_enabled", True)
    monkeypatch.setattr(settings, "courier_check_cache_hours", 24)
    monkeypatch.setattr(settings, "steadfast_api_key", SecretStr("test-steadfast-key"))
    monkeypatch.setattr(settings, "steadfast_secret_key", SecretStr("test-steadfast-secret"))
    monkeypatch.setattr("app.services.courier.service.open_client", _boom)
    old = datetime.now(UTC) - timedelta(hours=25)
    db_session.add(
        CourierCheckResult(
            phone=ADAPTER_PHONE,
            provider="steadfast",
            payload={
                "status": "ok",
                "total_parcels": 4,
                "delivered": 1,
                "returned_or_cancelled": 3,
                "success_rate": 0.25,
                "error_message": None,
            },
            checked_at=old,
        )
    )
    await db_session.commit()
    stale = await client.get(REPORT, headers=auth_headers, params={"phone": ADAPTER_PHONE})
    assert stale.status_code == 200, stale.text
    body = stale.json()["courier_check"]
    assert body["stale"] is True
    assert body["risk_level"] == "high"
    assert body["totals"]["delivered"] == 1
    assert body["totals"]["success_rate"] == 0.25
    steadfast = next(row for row in body["providers"] if row["provider"] == "steadfast")
    assert steadfast["status"] == "ok"
    assert steadfast["returned_or_cancelled"] == 3

    stored = await db_session.scalar(
        select(CourierCheckResult).where(CourierCheckResult.phone == ADAPTER_PHONE)
    )
    assert stored is not None
    stored.checked_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()
    fresh = await client.get(REPORT, headers=auth_headers, params={"phone": ADAPTER_PHONE})
    assert fresh.json()["courier_check"]["stale"] is False

    monkeypatch.setattr(settings, "pathao_username", "merchant@example.com")
    monkeypatch.setattr(settings, "pathao_password", SecretStr("test-pathao-password"))
    incomplete = await client.get(REPORT, headers=auth_headers, params={"phone": ADAPTER_PHONE})
    assert incomplete.json()["courier_check"]["stale"] is True
    pathao = next(
        row
        for row in incomplete.json()["courier_check"]["providers"]
        if row["provider"] == "pathao"
    )
    assert pathao["error_message"] == "No cached result"


async def test_live_check_isolates_providers_and_caches(
    client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "courier_check_enabled", True)
    monkeypatch.setattr(settings, "steadfast_api_key", SecretStr("test-steadfast-key"))
    monkeypatch.setattr(settings, "steadfast_secret_key", SecretStr("test-steadfast-secret"))
    monkeypatch.setattr(settings, "steadfast_base_url", "https://steadfast.test/api/v1")
    monkeypatch.setattr(settings, "pathao_username", "merchant@example.com")
    monkeypatch.setattr(settings, "pathao_password", SecretStr("test-pathao-password"))
    monkeypatch.setattr(settings, "pathao_base_url", "https://pathao.test")
    monkeypatch.setattr(settings, "redx_api_token", SecretStr("test-redx-token"))
    monkeypatch.setattr(settings, "redx_base_url", "https://redx.test")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "steadfast.test":
            assert request.headers["api-key"] == "test-steadfast-key"
            assert "test-steadfast-secret" not in str(request.url)
            return httpx.Response(
                200,
                json={"total_parcels": 10, "total_delivered": 8, "total_cancelled": 2},
            )
        if host == "pathao.test":
            if request.url.path.endswith("/login"):
                return httpx.Response(200, json={"access_token": "pathao-token"})
            return httpx.Response(500, json={"message": "down"})
        if host == "redx.test":
            raise httpx.ReadTimeout("slow", request=request)
        raise AssertionError(host)

    def factory(timeout: float) -> httpx.AsyncClient:
        calls["n"] += 1
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr("app.services.courier.service.open_client", factory)
    first = await client.post(REFRESH, headers=auth_headers, params={"phone": "+8801712345678"})
    assert first.status_code == 200, first.text
    by_name = {row["provider"]: row for row in first.json()["providers"]}
    assert by_name["steadfast"]["status"] == "ok"
    assert by_name["steadfast"]["success_rate"] == 0.8
    assert by_name["pathao"]["status"] == "error"
    assert by_name["pathao"]["error_message"] == "Pathao returned HTTP 500"
    assert by_name["redx"]["status"] == "error"
    assert by_name["redx"]["error_message"] == "Timed out"
    assert by_name["generic"]["status"] == "not_configured"
    assert first.json()["totals"]["delivered"] == 8
    assert first.json()["risk_level"] == "low"
    assert calls["n"] == 3

    again = await client.post(REFRESH, headers=auth_headers, params={"phone": ADAPTER_PHONE})
    assert again.status_code == 200, again.text
    stored = await db_session.scalar(
        select(func.count())
        .select_from(CourierCheckResult)
        .where(CourierCheckResult.phone == ADAPTER_PHONE)
    )
    assert stored == 3

    calls["n"] = 0
    monkeypatch.setattr("app.services.courier.service.open_client", _boom)
    cached = await client.get(REPORT, headers=auth_headers, params={"phone": ADAPTER_PHONE})
    assert cached.status_code == 200, cached.text
    cached_steadfast = next(
        row for row in cached.json()["courier_check"]["providers"] if row["provider"] == "steadfast"
    )
    assert cached_steadfast["delivered"] == 8


async def test_steadfast_success_error_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "steadfast_api_key", SecretStr("test-steadfast-key"))
    monkeypatch.setattr(settings, "steadfast_secret_key", SecretStr("test-steadfast-secret"))
    monkeypatch.setattr(settings, "steadfast_base_url", "https://steadfast.test/api/v1")
    provider = SteadfastProvider()

    def success(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/fraud_check/01712345678"
        assert request.headers["api-key"] == "test-steadfast-key"
        assert request.headers["secret-key"] == "test-steadfast-secret"
        return httpx.Response(
            200,
            json={"data": {"total_parcels": 24, "total_delivered": 9, "total_cancelled": 15}},
        )

    async with _http(success) as http:
        result = await provider.check(ADAPTER_PHONE, http)
    assert result.status == "ok"
    assert result.total_parcels == 24
    assert result.delivered == 9
    assert result.returned_or_cancelled == 15
    assert result.success_rate == 0.375

    async with _http(lambda _request: httpx.Response(401, json={"error": "no"})) as http:
        denied = await provider.check(ADAPTER_PHONE, http)
    assert denied.status == "error"
    assert denied.error_message == "Steadfast returned HTTP 401"

    async with _http(_timeout) as http:
        timed = await provider.check(ADAPTER_PHONE, http)
    assert timed.status == "error"
    assert timed.error_message == "Timed out"


async def test_pathao_success_error_timeout_and_hidden_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "pathao_username", "merchant@example.com")
    monkeypatch.setattr(settings, "pathao_password", SecretStr("test-pathao-password"))
    monkeypatch.setattr(settings, "pathao_base_url", "https://pathao.test")
    provider = PathaoProvider()
    seen: list[str] = []

    def success(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/login"):
            body = json.loads(request.content)
            assert body["username"] == "merchant@example.com"
            assert body["password"] == "test-pathao-password"
            return httpx.Response(200, json={"access_token": "pathao-token"})
        assert json.loads(request.content) == {"phone": ADAPTER_PHONE}
        assert request.headers["authorization"] == "Bearer pathao-token"
        assert "password" not in request.content.decode()
        return httpx.Response(
            200,
            json={"data": {"show_count": True, "successful_delivery": 5, "total_delivery": 6}},
        )

    async with _http(success) as http:
        result = await provider.check(ADAPTER_PHONE, http)
    assert result.status == "unverified"
    assert result.delivered == 5
    assert result.returned_or_cancelled == 1
    assert result.total_parcels == 6
    assert result.success_rate == 0.8333
    assert seen == ["/api/v1/login", "/api/v1/user/success"]

    def rating(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, json={"access_token": "pathao-token"})
        return httpx.Response(
            200,
            json={
                "data": {
                    "show_count": False,
                    "customer_rating": "excellent_customer",
                    "successful_delivery": 0,
                    "total_delivery": 0,
                }
            },
        )

    async with _http(rating) as http:
        hidden = await provider.check(ADAPTER_PHONE, http)
    assert hidden.status == "unverified"
    assert hidden.delivered is None
    assert hidden.total_parcels is None
    assert hidden.success_rate is None

    async with _http(lambda _request: httpx.Response(403, text="no")) as http:
        denied = await provider.check(ADAPTER_PHONE, http)
    assert denied.status == "error"
    assert denied.error_message == "Pathao authentication failed"

    async with _http(_timeout) as http:
        timed = await provider.check(ADAPTER_PHONE, http)
    assert timed.error_message == "Timed out"


async def test_redx_success_error_timeout_and_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "redx_api_token", SecretStr("test-redx-token"))
    monkeypatch.setattr(settings, "redx_phone", "")
    monkeypatch.setattr(settings, "redx_password", SecretStr(""))
    monkeypatch.setattr(settings, "redx_base_url", "https://redx.test")
    monkeypatch.setattr(settings, "redx_auth_header", "Authorization")
    provider = RedxProvider()

    def success(request: httpx.Request) -> httpx.Response:
        assert request.url.params["phoneNumber"] == "8801712345678"
        assert request.headers["authorization"] == "Bearer test-redx-token"
        return httpx.Response(200, json={"data": {"totalParcels": 4, "deliveredParcels": 3}})

    async with _http(success) as http:
        result = await provider.check(ADAPTER_PHONE, http)
    assert result.status == "unverified"
    assert result.total_parcels == 4
    assert result.delivered == 3
    assert result.returned_or_cancelled == 1
    assert result.success_rate == 0.75

    async with _http(lambda _request: httpx.Response(500, json={"message": "down"})) as http:
        broken = await provider.check(ADAPTER_PHONE, http)
    assert broken.error_message == "RedX returned HTTP 500"

    async with _http(
        lambda _request: httpx.Response(
            400, json={"data": {"totalParcels": 10, "deliveredParcels": 6}}
        )
    ) as http:
        dummy = await provider.check(ADAPTER_PHONE, http)
    assert dummy.error_message == "RedX customer lookup is unavailable"

    async with _http(_timeout) as http:
        timed = await provider.check(ADAPTER_PHONE, http)
    assert timed.error_message == "Timed out"

    monkeypatch.setattr(settings, "redx_phone", "01811111111")
    monkeypatch.setattr(settings, "redx_password", SecretStr("test-redx-password"))
    monkeypatch.setattr(settings, "redx_auth_url", "https://api.redx.test/v4/auth/login")

    def login(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.redx.test":
            body = json.loads(request.content)
            assert body["phone"] == "8801811111111"
            assert body["password"] == "test-redx-password"
            return httpx.Response(200, json={"data": {"accessToken": "session-token"}})
        assert request.headers["authorization"] == "Bearer session-token"
        return httpx.Response(200, json={"data": {"totalParcels": 2, "deliveredParcels": 2}})

    async with _http(login) as http:
        logged_in = await provider.check(ADAPTER_PHONE, http)
    assert logged_in.status == "unverified"
    assert logged_in.success_rate == 1.0


async def test_generic_success_error_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "courier_check_generic_url", "https://aggregator.test/check")
    monkeypatch.setattr(settings, "courier_check_generic_api_key", SecretStr("test-generic-key"))
    monkeypatch.setattr(settings, "courier_check_generic_auth_header", "api_key")
    provider = GenericProvider()

    def success(request: httpx.Request) -> httpx.Response:
        assert request.headers["api_key"] == "test-generic-key"
        assert "authorization" not in request.headers
        assert json.loads(request.content)["phone"] == ADAPTER_PHONE
        return httpx.Response(
            200,
            json={"data": {"totalSummary": {"total": 16, "success": 13, "cancel": 3}}},
        )

    async with _http(success) as http:
        result = await provider.check(ADAPTER_PHONE, http)
    assert result.status == "unverified"
    assert result.total_parcels == 16
    assert result.delivered == 13
    assert result.returned_or_cancelled == 3
    assert result.success_rate == 0.8125

    monkeypatch.setattr(settings, "courier_check_generic_auth_header", "Authorization")

    def flat(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-generic-key"
        return httpx.Response(
            200,
            json={"total_parcels": 2, "delivered": 1, "returned_or_cancelled": 1},
        )

    async with _http(flat) as http:
        direct = await provider.check(ADAPTER_PHONE, http)
    assert direct.success_rate == 0.5

    async with _http(lambda _request: httpx.Response(502, text="bad")) as http:
        broken = await provider.check(ADAPTER_PHONE, http)
    assert broken.error_message == "Generic provider returned HTTP 502"

    async with _http(_timeout) as http:
        timed = await provider.check(ADAPTER_PHONE, http)
    assert timed.error_message == "Timed out"

    assert GenericProvider().configured() is True
    monkeypatch.setattr(settings, "courier_check_generic_url", "http://aggregator.test/check")
    assert GenericProvider().configured() is False


def test_migration_0109_is_additive_on_current_head() -> None:
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0109_courier_check_results.py"
    spec = importlib.util.spec_from_file_location("migration_0109", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0109"
    assert module.down_revision == "0108"
    source = inspect.getsource(module.upgrade)
    assert "drop_" not in source
    assert "rename_" not in source
    assert "op.f(" in source
