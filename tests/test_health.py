import re
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from app.api.deps import get_db
from app.main import app
from app.middleware import client_request_id

_SERVER_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")


async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_checks_the_database(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}


async def test_readiness_is_503_when_the_database_is_down(client: AsyncClient) -> None:
    class _Down:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            raise ConnectionError("database down")

    async def _down() -> AsyncIterator[_Down]:
        yield _Down()

    app.dependency_overrides[get_db] = _down
    live = await client.get("/health/live")
    ready = await client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "unavailable",
        "database": "unreachable",
        "redis": "ok",
    }


async def test_readiness_is_503_when_redis_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.v1.endpoints.health.rate_limit_store_ready", lambda: False)

    live = await client.get("/health/live")
    ready = await client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable", "database": "ok", "redis": "unreachable"}


async def test_request_id_header_is_returned(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert _SERVER_REQUEST_ID.fullmatch(response.headers["X-Request-ID"])
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_request_id_ignores_the_client_value(client: AsyncClient) -> None:
    supplied = "client-supplied-id"
    first = await client.get("/health/live", headers={"X-Request-ID": supplied})
    second = await client.get("/health/live", headers={"X-Request-ID": supplied})

    assert first.headers["X-Request-ID"] != supplied
    assert second.headers["X-Request-ID"] != supplied
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    assert _SERVER_REQUEST_ID.fullmatch(first.headers["X-Request-ID"])


def test_client_request_id_keeps_only_a_safe_token() -> None:
    assert client_request_id(" client-supplied-id ") == "client-supplied-id"
    assert client_request_id("bad\nid") is None
    assert client_request_id("") is None
