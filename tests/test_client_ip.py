import pytest
from starlette.requests import Request

from app.api.deps import client_ip
from app.core.config import settings


def _request(peer: str, headers: dict[str, str]) -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
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
            "client": (peer, 50000),
            "server": ("testserver", 80),
        }
    )


@pytest.fixture
def trusted_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxies", ["10.0.0.5"])


def test_direct_client_cannot_choose_its_address() -> None:
    request = _request(
        "203.0.113.8",
        {"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "8.8.8.8, 1.1.1.1"},
    )
    assert client_ip(request) == "203.0.113.8"


def test_trusted_proxy_uses_the_address_it_appended(trusted_proxy: None) -> None:
    request = _request("10.0.0.5", {"X-Forwarded-For": "1.2.3.4, 198.51.100.10"})
    assert client_ip(request) == "198.51.100.10"
    assert trusted_proxy is None


def test_spoofed_cloudflare_header_loses_to_the_appended_address(trusted_proxy: None) -> None:
    request = _request(
        "10.0.0.5",
        {"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "1.2.3.4, 198.51.100.10"},
    )
    assert client_ip(request) == "198.51.100.10"
    assert trusted_proxy is None


def test_cloudflare_header_is_used_when_the_proxy_set_only_that(trusted_proxy: None) -> None:
    request = _request("10.0.0.5", {"CF-Connecting-IP": "198.51.100.10"})
    assert client_ip(request) == "198.51.100.10"
    assert trusted_proxy is None


def test_a_network_of_every_address_is_not_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_proxies", ["0.0.0.0/0"])
    request = _request("203.0.113.8", {"X-Forwarded-For": "1.2.3.4"})
    assert client_ip(request) == "203.0.113.8"
