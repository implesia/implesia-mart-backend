"""Courier history provider contract and shared parsing.

A provider turns one normalized phone into parcel counts. The rate is always
computed here from those counts. Adapters do not trust a rate sent by the courier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

ProviderStatus = Literal["not_configured", "ok", "error", "unverified"]

_HEADER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_COUNT = 1_000_000


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider: str
    status: ProviderStatus
    total_parcels: int | None = None
    delivered: int | None = None
    returned_or_cancelled: int | None = None
    success_rate: float | None = None
    error_message: str | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "total_parcels": self.total_parcels,
            "delivered": self.delivered,
            "returned_or_cancelled": self.returned_or_cancelled,
            "success_rate": self.success_rate,
            "error_message": self.error_message,
        }


class CourierHistoryProvider(Protocol):
    """One courier. `check` performs the HTTP call. It does not read the cache."""

    name: str
    verified: bool

    def configured(self) -> bool:
        """True when the env keys needed for a live call are set."""

    async def check(self, phone: str, client: httpx.AsyncClient) -> ProviderResult:
        """Look up `phone` (already `01XXXXXXXXX`). Do not log secrets or the phone."""


def success_ratio(delivered: int, failed: int) -> float | None:
    """Delivered / (delivered + returned or cancelled). Null when nothing has finished."""
    finished = delivered + failed
    if finished <= 0:
        return None
    return round(delivered / finished, 4)


def not_configured(name: str) -> ProviderResult:
    return ProviderResult(provider=name, status="not_configured")


def failed(name: str, message: str) -> ProviderResult:
    return ProviderResult(provider=name, status="error", error_message=message[:200])


def counted(
    name: str,
    *,
    status: ProviderStatus,
    total: int | None,
    delivered: int | None,
    failed_count: int | None,
) -> ProviderResult:
    rate = None
    if delivered is not None and failed_count is not None:
        rate = success_ratio(delivered, failed_count)
    return ProviderResult(
        provider=name,
        status=status,
        total_parcels=total,
        delivered=delivered,
        returned_or_cancelled=failed_count,
        success_rate=rate,
    )


def secret_text(value: SecretStr) -> str:
    return value.get_secret_value().strip()


def https_url(value: str) -> str | None:
    """An https URL with no embedded user or password. Empty and http are refused."""
    raw = value.strip()
    if not raw or any(char in raw for char in "\r\n\t "):
        return None
    parts = urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    return raw.rstrip("/") if not parts.query and not parts.fragment else raw


def header_name(value: str) -> str | None:
    name = value.strip() or "Authorization"
    if _HEADER_NAME.fullmatch(name) is None:
        return None
    return name


def bearer(token: str) -> str:
    cleaned = token.strip()
    if cleaned.lower().startswith("bearer "):
        return cleaned
    return f"Bearer {cleaned}"


def as_count(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    number: int | None = None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    if number is None or number < 0 or number > _MAX_COUNT:
        return None
    return number


def as_dict(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def first_count(source: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key in source:
            found = as_count(source.get(key))
            if found is not None:
                return found
    return None
