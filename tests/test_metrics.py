import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from app.core.config import settings
from app.metrics import observe_request

TOKEN = "scrape-token-123"
SCRAPE = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def metrics_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_token", SecretStr(TOKEN))


def _value(body: str, name: str) -> float:
    for line in body.splitlines():
        if line.startswith("#"):
            continue
        head, _, raw = line.partition(" ")
        if head == name:
            return float(raw)
    raise AssertionError(name)


async def test_metrics_counts_401_and_skips_probes(client: AsyncClient) -> None:
    before = (await client.get("/metrics", headers=SCRAPE)).text
    denied = await client.get("/api/v1/auth/me")
    probe = await client.get("/health/live")
    after = (await client.get("/metrics", headers=SCRAPE)).text

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
    before = (await client.get("/metrics", headers=SCRAPE)).text
    observe_request("/api/v1/orders", 503, 0.2)
    observe_request("/api/v1/auth/login", 429, 0.01)
    observe_request("/health/ready", 500, 1.0)
    after = (await client.get("/metrics", headers=SCRAPE)).text

    assert _value(after, "http_responses_5xx_total") == (
        _value(before, "http_responses_5xx_total") + 1
    )
    assert _value(after, "http_responses_429_total") == (
        _value(before, "http_responses_429_total") + 1
    )
    assert _value(after, "http_requests_total") == _value(before, "http_requests_total") + 2


async def test_metrics_reports_database_and_redis(client: AsyncClient) -> None:
    response = await client.get("/metrics", headers=SCRAPE)
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
    body = (await client.get("/metrics", headers=SCRAPE)).text
    assert _value(body, "database_up") == 0
    assert _value(body, "redis_up") == 0


async def test_metrics_rejects_anonymous_missing_and_invalid_tokens(client: AsyncClient) -> None:
    assert (await client.get("/metrics")).status_code == 404
    for header in ("Bearer nope", "Bearer ", TOKEN, f"Basic {TOKEN}", f"Bearer {TOKEN}x"):
        response = await client.get("/metrics", headers={"Authorization": header})
        assert response.status_code == 404, header
        assert TOKEN not in response.text
    ok = await client.get("/metrics", headers=SCRAPE)
    assert ok.status_code == 200
    assert TOKEN not in ok.text


@pytest.mark.parametrize("environment", ["local", "staging", "production"])
async def test_metrics_disabled_without_a_token_in_every_environment(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setattr(settings, "metrics_token", SecretStr(""))
    monkeypatch.setattr(settings, "environment", environment)
    assert (await client.get("/metrics")).status_code == 404
    assert (await client.get("/metrics", headers={"Authorization": "Bearer "})).status_code == 404


async def test_metrics_with_token_works_in_production(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    assert (await client.get("/metrics")).status_code == 404
    assert (await client.get("/metrics", headers=SCRAPE)).status_code == 200


def test_metrics_token_is_not_in_settings_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TOKEN not in repr(settings)
    assert TOKEN not in str(settings.model_dump())


def test_metrics_have_no_per_path_labels() -> None:
    observe_request("/api/v1/orders/123e4567-e89b-12d3-a456-426614174000", 200, 0.01)
    from prometheus_client import REGISTRY

    for family in REGISTRY.collect():
        for sample in family.samples:
            assert "path" not in sample.labels
            assert "123e4567" not in str(sample.labels)
