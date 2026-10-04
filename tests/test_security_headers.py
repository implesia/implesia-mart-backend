import pytest
from httpx import AsyncClient

from app.core.config import settings

BASELINE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


async def test_local_responses_keep_the_baseline_headers(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    for header, value in BASELINE_HEADERS.items():
        assert response.headers[header] == value
    assert "Strict-Transport-Security" not in response.headers
    assert "Content-Security-Policy" not in response.headers


async def test_production_adds_hsts_and_frame_ancestors(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "production")

    response = await client.get("/health/live")

    for header, value in BASELINE_HEADERS.items():
        assert response.headers[header] == value
    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
