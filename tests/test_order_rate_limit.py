import uuid

import pytest
from httpx import AsyncClient
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

from app.api.v1.endpoints import orders as orders_endpoint
from app.rate_limit import limiter
from tests.test_orders import SHIPPING
from tests.test_products import _create


@pytest.fixture
def order_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limiter, "enabled", True)
    monkeypatch.setattr(limiter, "_limiter", FixedWindowRateLimiter(MemoryStorage()))
    monkeypatch.setattr(orders_endpoint, "_ORDER_LIMIT", parse("2/hour"))


async def test_only_placed_orders_spend_the_budget(
    client: AsyncClient, auth_headers: dict[str, str], order_limit: None
) -> None:
    product = await _create(client, auth_headers, title="Budget lamp", price=300, quantity=10)
    body = {"source": "direct", "items": [{"product_id": product["id"], "quantity": 1}]}

    for _ in range(3):  # rejected submissions do not count
        bad = await client.post(
            "/api/v1/orders",
            headers={**auth_headers, "Idempotency-Key": uuid.uuid4().hex},
            json={**body, **SHIPPING, "district": "x" * 2, "area": "y" * 2, "items": []},
        )
        assert bad.status_code == 422

    key = uuid.uuid4().hex
    first = await client.post(
        "/api/v1/orders",
        headers={**auth_headers, "Idempotency-Key": key},
        json={**body, **SHIPPING},
    )
    assert first.status_code == 201, first.text
    for _ in range(3):  # replays do not count
        again = await client.post(
            "/api/v1/orders",
            headers={**auth_headers, "Idempotency-Key": key},
            json={**body, **SHIPPING},
        )
        assert again.json()["id"] == first.json()["id"]

    second = await client.post(
        "/api/v1/orders",
        headers={**auth_headers, "Idempotency-Key": uuid.uuid4().hex},
        json={**body, **SHIPPING},
    )
    assert second.status_code == 201, second.text
    third = await client.post(
        "/api/v1/orders",
        headers={**auth_headers, "Idempotency-Key": uuid.uuid4().hex},
        json={**body, **SHIPPING},
    )
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "rate_limited"
