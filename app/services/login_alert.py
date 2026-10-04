"""Raise one log alert when failed logins bunch up.

An expired access token is not a login attempt. Workers share the window
through Redis. Without Redis, each process keeps its own window.
"""

import asyncio
import hashlib
import threading
import time

import redis

from app.core.config import settings
from app.core.logging import get_logger
from app.metrics import ADMIN_LOGIN_FAILURES, LOGIN_ALERTS, LOGIN_FAILURES
from app.models.user import UserRole

logger = get_logger("auth")

ADMIN_THRESHOLD = 5
ADMIN_WINDOW_SECONDS = 600
SPIKE_THRESHOLD = 20
SPIKE_WINDOW_SECONDS = 300

_REDIS_URLS = ("redis://", "rediss://", "redis+unix://", "unix://")
_lock = threading.Lock()
_windows: dict[str, tuple[float, int]] = {}


def clear() -> None:
    """Drop the in-process window. Tests use this; Redis keys expire on their own."""
    with _lock:
        _windows.clear()


def _admin(email: str, role: UserRole | None) -> bool:
    if email == settings.first_superuser_email.lower():
        return True
    return role == UserRole.SUPERADMIN


def _local_count(key: str, window: int) -> int:
    now = time.monotonic()
    with _lock:
        started, count = _windows.get(key, (now, 0))
        if now - started >= window:
            started, count = now, 0
        count += 1
        _windows[key] = (started, count)
        return count


def _redis_count(key: str, window: int) -> int:
    url = settings.redis_url.replace("redis+unix://", "unix://", 1)
    client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
    try:
        count = int(client.incr(key))
        if client.ttl(key) < 0:
            client.expire(key, window)
        return count
    finally:
        client.close()


def _count(key: str, window: int) -> int:
    if settings.redis_url.startswith(_REDIS_URLS):
        try:
            return _redis_count(key, window)
        except Exception:
            return _local_count(key, window)
    return _local_count(key, window)


def _alert(kind: str, email: str, failures: int, window: int) -> None:
    LOGIN_ALERTS.labels(kind=kind).inc()
    logger.error(
        "failed_login_alert",
        kind=kind,
        email=email,
        failures=failures,
        window_seconds=window,
    )


def record_failure(email: str, role: UserRole | None) -> list[str]:
    """Count this failure. Return the alert kinds this attempt crossed."""
    normalized = email.lower()
    LOGIN_FAILURES.inc()
    raised: list[str] = []
    if _admin(normalized, role):
        ADMIN_LOGIN_FAILURES.inc()
        digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
        count = _count(f"implesia:admin_login_failures:{digest}", ADMIN_WINDOW_SECONDS)
        if count == ADMIN_THRESHOLD:
            _alert("admin", normalized, count, ADMIN_WINDOW_SECONDS)
            raised.append("admin")
    count = _count("implesia:login_failures", SPIKE_WINDOW_SECONDS)
    if count == SPIKE_THRESHOLD:
        _alert("spike", normalized, count, SPIKE_WINDOW_SECONDS)
        raised.append("spike")
    return raised


async def note_failure(email: str, role: UserRole | None) -> None:
    try:
        await asyncio.to_thread(record_failure, email, role)
    except Exception:
        logger.warning("failed_login_alert_failed")
