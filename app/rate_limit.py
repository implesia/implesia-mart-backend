import json

import redis
from fastapi import Request
from slowapi import Limiter

from app.api.deps import client_ip
from app.core.config import settings
from app.core.security import InvalidTokenError, decode_token


def _rate_limit_key(request: Request) -> str:
    return client_ip(request) or "anonymous"


def _json_object(request: Request) -> dict[str, object]:
    raw = getattr(request, "_body", b"") or b""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def login_account_key(request: Request) -> str:
    """One bucket per email, so a new address does not reset the password guesses."""
    email = str(_json_object(request).get("email") or "").strip().lower()
    if not email:
        return f"login-account:{_rate_limit_key(request)}"
    return f"login-account:{email}"


def refresh_account_key(request: Request) -> str:
    """One bucket per account named in a signed refresh token."""
    token = str(_json_object(request).get("refresh_token") or "")
    subject = _refresh_subject(token)
    if subject is None:
        return f"refresh-account:{_rate_limit_key(request)}"
    return f"refresh-account:{subject}"


def _refresh_subject(token: str) -> str | None:
    if not token:
        return None
    try:
        payload = decode_token(token, "refresh", verify_exp=False)
    except InvalidTokenError:
        return None
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        return None
    return subject


# Redis storage keeps limits consistent across Gunicorn workers. There is no
# in-memory fallback: if Redis is down, limited routes cannot share one counter.
limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.redis_url,
    enabled=settings.environment != "test",
)

_REDIS_URLS = ("redis://", "rediss://", "redis+unix://", "unix://")


def rate_limit_store_ready() -> bool:
    """The configured limit store answers. In-process memory storage always does."""
    url = settings.redis_url
    if not url.startswith(_REDIS_URLS):
        try:
            return bool(limiter._storage.check())
        except Exception:
            return False
    client = redis.Redis.from_url(
        url.replace("redis+unix://", "unix://", 1),
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        return bool(client.ping())
    except Exception:
        return False
    finally:
        client.close()
