"""Cloudflare Turnstile siteverify for public checkout.

Only ``POST /api/v1/orders`` calls this. Admin and offline orders do not.
The secret and the token are never logged. Siteverify is not called from tests
against the real network: tests replace ``httpx.AsyncClient``.

When ``TURNSTILE_SECRET_KEY`` is empty and ``ENVIRONMENT`` is not production,
verification is skipped and a debug line is logged. Production with an empty
secret refuses the order.
"""

import ipaddress
from typing import Any

import httpx
from starlette.requests import Request

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger("turnstile")

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
HTTP_TIMEOUT = httpx.Timeout(5.0)
FAILED_MESSAGE = "নিরাপত্তা যাচাই ব্যর্থ হয়েছে, আবার চেষ্টা করুন"
_TOKEN_MAX = 2048


class TurnstileFailed(AppError):
    """Public checkout did not pass Turnstile. Status 400."""

    code = "turnstile_failed"

    def __init__(self) -> None:
        super().__init__(FAILED_MESSAGE)


def _secret() -> str:
    return settings.turnstile_secret_key.strip()


def _remote_ip(request: Request) -> str | None:
    """``CF-Connecting-IP`` only. Omitted when the header is missing or not an IP."""
    raw = (request.headers.get("cf-connecting-ip") or "").strip()
    if not raw:
        return None
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        return None
    return raw


async def verify_checkout(request: Request, token: str | None) -> None:
    """Require a valid Turnstile token before a new public order is placed.

    A replay of an existing idempotency key must not call this. Raises
    ``TurnstileFailed`` when the token is missing, rejected, or the siteverify
    call cannot be completed. Does nothing when the secret is unset outside
    production.
    """
    secret = _secret()
    if not secret:
        if settings.is_production:
            logger.error(
                "turnstile_not_configured",
                detail=(
                    "TURNSTILE_SECRET_KEY is unset; refusing public checkout in production"
                ),
            )
            raise TurnstileFailed()
        logger.debug(
            "turnstile_skipped",
            detail="TURNSTILE_SECRET_KEY is unset; skipping verification outside production",
        )
        return

    cleaned = (token or "").strip()
    if not cleaned or len(cleaned) > _TOKEN_MAX:
        raise TurnstileFailed()

    form: dict[str, str] = {"secret": secret, "response": cleaned}
    remote_ip = _remote_ip(request)
    if remote_ip is not None:
        form["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
            response = await client.post(SITEVERIFY_URL, data=form)
            payload: Any = response.json()
    except (httpx.HTTPError, ValueError):
        logger.error("turnstile_siteverify_failed", error_type="network")
        raise TurnstileFailed() from None

    accepted = (
        response.status_code < 400
        and isinstance(payload, dict)
        and payload.get("success") is True
    )
    if not accepted:
        logger.warning("turnstile_rejected")
        raise TurnstileFailed()
