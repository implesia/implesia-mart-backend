import re

from httpx import AsyncClient

from app.main import app

_PARAM = "00000000-0000-4000-8000-000000000001"
_METHODS = {"get", "post", "put", "patch", "delete"}


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", _PARAM, path)


def _admin_calls() -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/v1/admin") and not path.startswith("/api/v1/users"):
            continue
        for method in sorted(operations):
            if method in _METHODS:
                calls.append((method.upper(), path))
    return calls


async def test_every_admin_route_rejects_a_missing_token(client: AsyncClient) -> None:
    calls = _admin_calls()
    assert len(calls) >= 40
    for method, path in calls:
        response = await client.request(method, _concrete(path))
        assert response.status_code == 401, (method, path, response.status_code, response.text)
        assert "error" in response.json()


async def test_a_garbage_bearer_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/admin/products",
        headers={"Authorization": "Bearer not-a-token"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
