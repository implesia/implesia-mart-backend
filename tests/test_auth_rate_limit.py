from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.rate_limit import limiter
from tests.conftest import TEST_PASSWORD

WRONG_PASSWORD = "wrong-password-entirely"


@contextmanager
def enforced_limits() -> Iterator[None]:
    limiter.reset()
    limiter.enabled = True
    try:
        yield
    finally:
        limiter.enabled = False
        limiter.reset()


@pytest.fixture(autouse=True)
def _limits_off_after_test() -> Iterator[None]:
    yield
    limiter.enabled = False
    limiter.reset()


async def test_login_is_limited_per_address(client: AsyncClient) -> None:
    with enforced_limits():
        for index in range(10):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": f"guess{index}@example.com", "password": WRONG_PASSWORD},
            )
            assert response.status_code == 401, response.text
        blocked = await client.post(
            "/api/v1/auth/login",
            json={"email": "another@example.com", "password": WRONG_PASSWORD},
        )
    assert blocked.status_code == 429
    assert blocked.json() == {
        "error": {"code": "rate_limited", "message": "Too many requests."}
    }
    assert "per" not in blocked.text


async def test_spoofed_ip_headers_do_not_bypass_the_address_limit(client: AsyncClient) -> None:
    with enforced_limits():
        for index in range(10):
            response = await client.post(
                "/api/v1/auth/login",
                headers={
                    "X-Forwarded-For": f"198.51.100.{index + 1}",
                    "CF-Connecting-IP": f"203.0.113.{index + 1}",
                },
                json={"email": f"spoof{index}@example.com", "password": WRONG_PASSWORD},
            )
            assert response.status_code == 401, response.text
        blocked = await client.post(
            "/api/v1/auth/login",
            headers={
                "X-Forwarded-For": "198.51.100.250",
                "CF-Connecting-IP": "203.0.113.250",
            },
            json={"email": "fresh@example.com", "password": WRONG_PASSWORD},
        )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


async def test_login_is_limited_per_email_across_addresses(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trusted_proxies", ["127.0.0.1"])
    with enforced_limits():
        for index in range(10):
            response = await client.post(
                "/api/v1/auth/login",
                headers={"X-Forwarded-For": f"198.51.100.{index + 1}"},
                json={"email": "target@example.com", "password": WRONG_PASSWORD},
            )
            assert response.status_code == 401, response.text
        blocked = await client.post(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": "198.51.100.200"},
            json={"email": "Target@Example.com", "password": WRONG_PASSWORD},
        )
        other = await client.post(
            "/api/v1/auth/login",
            headers={"X-Forwarded-For": "198.51.100.201"},
            json={"email": "someone-else@example.com", "password": WRONG_PASSWORD},
        )
    assert blocked.status_code == 429
    assert other.status_code == 401


async def test_refresh_is_limited_per_address(
    client: AsyncClient, superadmin_token: str
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    token = login.json()["refresh_token"]
    with enforced_limits():
        for _ in range(10):
            response = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
            assert response.status_code == 200, response.text
            token = response.json()["refresh_token"]
        blocked = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert blocked.status_code == 429
    assert superadmin_token


async def test_refresh_is_limited_per_account_across_addresses(
    client: AsyncClient, superadmin_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "trusted_proxies", ["127.0.0.1"])
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    token = login.json()["refresh_token"]
    with enforced_limits():
        for index in range(10):
            response = await client.post(
                "/api/v1/auth/refresh",
                headers={"X-Forwarded-For": f"203.0.113.{index + 1}"},
                json={"refresh_token": token},
            )
            assert response.status_code == 200, response.text
            token = response.json()["refresh_token"]
        blocked = await client.post(
            "/api/v1/auth/refresh",
            headers={"X-Forwarded-For": "203.0.113.200"},
            json={"refresh_token": token},
        )
    assert blocked.status_code == 429
    assert superadmin_token
