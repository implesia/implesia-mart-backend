import pytest
from httpx import AsyncClient

from app.metrics import observe_request


def _value(body: str, name: str) -> float:
    for line in body.splitlines():
        if line.startswith("#"):
            continue
        head, _, raw = line.partition(" ")
        if head == name:
            return float(raw)
    raise AssertionError(name)


async def test_metrics_counts_401_and_skips_probes(client: AsyncClient) -> None:
    before = (await client.get("/metrics")).text
    denied = await client.get("/api/v1/auth/me")
    probe = await client.get("/health/live")
    after = (await client.get("/metrics")).text

    assert denied.status_code == 401
    assert probe.status_code == 200
    assert _value(after, "http_requests_total") == _value(before, "http_requests_total") + 1
    assert _value(after, "http_responses_401_total") == (
        _value(before, "http_responses_401_total") + 1
    )
    assert _value(after, "http_responses_5xx_total") == _value(before, "http_responses_5xx_total")
    assert (
        _value(after, "http_request_duration_seconds_count")
        == _value(before, "http_request_duration_seconds_count") + 1
    )


async def test_metrics_counts_5xx_and_429(client: AsyncClient) -> None:
    before = (await client.get("/metrics")).text
    observe_request("/api/v1/orders", 503, 0.2)
    observe_request("/api/v1/auth/login", 429, 0.01)
    observe_request("/health/ready", 500, 1.0)
    after = (await client.get("/metrics")).text

    assert _value(after, "http_responses_5xx_total") == (
        _value(before, "http_responses_5xx_total") + 1
    )
    assert _value(after, "http_responses_429_total") == (
        _value(before, "http_responses_429_total") + 1
    )
    assert _value(after, "http_requests_total") == _value(before, "http_requests_total") + 2


async def test_metrics_reports_database_and_redis(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert _value(body, "database_up") == 1
    assert _value(body, "redis_up") == 1


async def test_metrics_reports_a_down_dependency(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down() -> bool:
        return False

    monkeypatch.setattr("app.api.v1.endpoints.metrics.database_up", down)
    monkeypatch.setattr("app.api.v1.endpoints.metrics.rate_limit_store_ready", lambda: False)
    body = (await client.get("/metrics")).text
    assert _value(body, "database_up") == 0
    assert _value(body, "redis_up") == 0
