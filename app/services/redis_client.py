"""Resilient async Redis client with bounded pooling and transparent in-memory fallback.

Supports:
- Single-use 30-second WebSocket auth tickets (`ws:ticket:{token}`, consumed via atomic GETDEL)
- Lightweight user presence (`presence:user:{user_id}`, 60s TTL, zero PostgreSQL writes)
- Sliding-window per-user WebSocket rate limiting (`rl:ws:{user_id}`, default 20 events / 10s)
- Pub/Sub publishing & raw client access for the worker subscriber loop

When Redis is disabled (`memory://` in tests) or temporarily unreachable, operations degrade
gracefully to an in-process memory store with a single startup warning so the monolith never
crashes.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_CONNECTIONS = 50
_SOCKET_TIMEOUT = 5.0
_SOCKET_CONNECT_TIMEOUT = 3.0

_TICKET_PREFIX = "ws:ticket:"
_PRESENCE_PREFIX = "presence:user:"
_LAST_SEEN_PREFIX = "last_seen:user:"
_LAST_SEEN_TTL_SECONDS = 30 * 86400
_RATE_LIMIT_PREFIX = "rl:ws:"
_CHAT_RATE_LIMIT_PREFIX = "rl:chat:"
_CHAT_NOTIFY_PREFIX = "chat:notify:"


def _is_memory_url(url: str) -> bool:
    cleaned = url.strip().lower()
    return not cleaned or cleaned.startswith("memory://")


class AsyncRedisClient:
    """Singleton async Redis wrapper with safe in-process fallback."""

    def __init__(self) -> None:
        self._pool: aioredis.ConnectionPool | None = None
        self._client: aioredis.Redis | None = None
        self._connected: bool = False
        self._warned_fallback: bool = False

        # In-process fallback state (used in SQLite/memory:// tests or Redis outage)
        self._mem_tickets: dict[str, tuple[float, dict[str, Any]]] = {}
        self._mem_presence: dict[str, float] = {}
        self._mem_last_seen: dict[str, str] = {}
        self._mem_rate: dict[str, deque[float]] = {}
        self._mem_chat_rate: dict[str, deque[float]] = {}
        self._mem_notify_throttle: dict[str, float] = {}
        self._mem_kv: dict[str, tuple[float, str]] = {}

    @property
    def is_redis_available(self) -> bool:
        return self._connected and self._client is not None

    def raw_client(self) -> aioredis.Redis | None:
        return self._client if self._connected else None

    def _warn_once(self, reason: str) -> None:
        if not self._warned_fallback:
            self._warned_fallback = True
            logger.warning(
                "redis_realtime_fallback",
                reason=reason,
                mode="in_process_memory",
            )

    async def connect(self) -> bool:
        """Initialize the bounded async Redis connection pool and verify connectivity."""
        url = settings.redis_url.strip()
        if _is_memory_url(url):
            self._connected = False
            self._warn_once("redis_url_is_memory_or_empty")
            return False

        if self._connected and self._client is not None:
            return True

        try:
            self._pool = aioredis.ConnectionPool.from_url(
                url,
                max_connections=_MAX_CONNECTIONS,
                socket_timeout=_SOCKET_TIMEOUT,
                socket_connect_timeout=_SOCKET_CONNECT_TIMEOUT,
                decode_responses=True,
                health_check_interval=30,
            )
            client = aioredis.Redis(connection_pool=self._pool)
            await client.ping()
            self._client = client
            self._connected = True
            self._warned_fallback = False
            logger.info("redis_realtime_connected", max_connections=_MAX_CONNECTIONS)
            return True
        except (RedisError, OSError, ValueError) as exc:
            self._connected = False
            await self._cleanup_client()
            self._warn_once(f"connect_failed: {exc}")
            return False

    async def _cleanup_client(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.aclose()
            self._client = None
        if self._pool is not None:
            with contextlib.suppress(Exception):
                await self._pool.disconnect()
            self._pool = None

    async def close(self) -> None:
        self._connected = False
        await self._cleanup_client()

    def reset_memory_state(self) -> None:
        """Clear in-process fallback stores (used by test fixtures)."""
        self._mem_tickets.clear()
        self._mem_presence.clear()
        self._mem_last_seen.clear()
        self._mem_rate.clear()
        self._mem_chat_rate.clear()
        self._mem_notify_throttle.clear()
        self._mem_kv.clear()

    def _prune_mem_tickets(self, now: float) -> None:
        expired = [k for k, (exp, _) in self._mem_tickets.items() if exp <= now]
        for key in expired:
            self._mem_tickets.pop(key, None)

    async def issue_ws_ticket(
        self,
        payload: dict[str, Any],
        *,
        ttl_seconds: int = 30,
    ) -> str:
        """Store a single-use short-lived WebSocket authentication ticket."""
        token = secrets.token_urlsafe(32)
        key = f"{_TICKET_PREFIX}{token}"
        serialized = json.dumps(payload, separators=(",", ":"))

        if self._connected and self._client is not None:
            try:
                await self._client.set(key, serialized, ex=ttl_seconds)
                return token
            except (RedisError, OSError) as exc:
                self._warn_once(f"ticket_set_failed: {exc}")

        now = time.monotonic()
        self._prune_mem_tickets(now)
        self._mem_tickets[token] = (now + ttl_seconds, dict(payload))
        return token

    async def consume_ws_ticket(self, token: str) -> dict[str, Any] | None:
        """Atomically consume a WebSocket ticket (single-use via GETDEL)."""
        cleaned = token.strip()
        if not cleaned or len(cleaned) > 128:
            return None

        key = f"{_TICKET_PREFIX}{cleaned}"
        if self._connected and self._client is not None:
            try:
                raw = await self._client.getdel(key)
                if raw is not None:
                    parsed = json.loads(raw)
                    return parsed if isinstance(parsed, dict) else None
                # Also check memory fallback in case ticket was issued during transient outage
            except (RedisError, OSError, json.JSONDecodeError) as exc:
                self._warn_once(f"ticket_getdel_failed: {exc}")

        now = time.monotonic()
        entry = self._mem_tickets.pop(cleaned, None)
        if entry is None:
            return None
        expires_at, data = entry
        if expires_at <= now:
            return None
        return data

    async def set_presence(self, user_id: str, *, ttl_seconds: int = 60) -> str:
        """Refresh online presence TTL and last_seen timestamp (zero Postgres writes)."""
        now_iso = datetime.now(UTC).isoformat()
        key = f"{_PRESENCE_PREFIX}{user_id}"
        last_seen_key = f"{_LAST_SEEN_PREFIX}{user_id}"
        if self._connected and self._client is not None:
            try:
                async with self._client.pipeline(transaction=False) as pipe:
                    pipe.set(key, "1", ex=ttl_seconds)
                    pipe.set(last_seen_key, now_iso, ex=_LAST_SEEN_TTL_SECONDS)
                    await pipe.execute()
                return now_iso
            except (RedisError, OSError) as exc:
                self._warn_once(f"presence_set_failed: {exc}")

        self._mem_presence[user_id] = time.monotonic() + ttl_seconds
        self._mem_last_seen[user_id] = now_iso
        return now_iso

    async def clear_presence(self, user_id: str) -> str:
        """Remove online flag and record exact offline timestamp in last_seen."""
        now_iso = datetime.now(UTC).isoformat()
        key = f"{_PRESENCE_PREFIX}{user_id}"
        last_seen_key = f"{_LAST_SEEN_PREFIX}{user_id}"
        if self._connected and self._client is not None:
            try:
                async with self._client.pipeline(transaction=False) as pipe:
                    pipe.delete(key)
                    pipe.set(last_seen_key, now_iso, ex=_LAST_SEEN_TTL_SECONDS)
                    await pipe.execute()
            except (RedisError, OSError) as exc:
                self._warn_once(f"presence_delete_failed: {exc}")
        self._mem_presence.pop(user_id, None)
        self._mem_last_seen[user_id] = now_iso
        return now_iso

    @staticmethod
    def _parse_iso_datetime(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        except ValueError:
            return None

    async def get_last_seen(self, user_id: str) -> datetime | None:
        key = f"{_LAST_SEEN_PREFIX}{user_id}"
        if self._connected and self._client is not None:
            try:
                raw = await self._client.get(key)
                if isinstance(raw, str):
                    return self._parse_iso_datetime(raw)
                return None
            except (RedisError, OSError) as exc:
                self._warn_once(f"last_seen_get_failed: {exc}")
        return self._parse_iso_datetime(self._mem_last_seen.get(user_id))

    async def get_last_seen_map(self, user_ids: set[str] | list[str]) -> dict[str, datetime | None]:
        """Batch-fetch last_seen timestamps for multiple user IDs via a single Redis MGET."""
        unique_ids = [uid for uid in dict.fromkeys(user_ids) if uid]
        if not unique_ids:
            return {}

        if self._connected and self._client is not None:
            try:
                keys = [f"{_LAST_SEEN_PREFIX}{uid}" for uid in unique_ids]
                values = await self._client.mget(keys)
                return {
                    uid: self._parse_iso_datetime(val if isinstance(val, str) else None)
                    for uid, val in zip(unique_ids, values, strict=False)
                }
            except (RedisError, OSError) as exc:
                self._warn_once(f"last_seen_mget_failed: {exc}")

        return {
            uid: self._parse_iso_datetime(self._mem_last_seen.get(uid))
            for uid in unique_ids
        }

    async def is_user_online(self, user_id: str) -> bool:
        key = f"{_PRESENCE_PREFIX}{user_id}"
        if self._connected and self._client is not None:
            try:
                exists = await self._client.exists(key)
                if exists:
                    return True
            except (RedisError, OSError) as exc:
                self._warn_once(f"presence_check_failed: {exc}")

        exp = self._mem_presence.get(user_id)
        if exp is None:
            return False
        if exp <= time.monotonic():
            self._mem_presence.pop(user_id, None)
            return False
        return True

    async def get_online_user_ids(self, user_ids: set[str] | list[str]) -> set[str]:
        """Batch-check online presence for multiple user IDs via a single Redis MGET."""
        unique_ids = [uid for uid in dict.fromkeys(user_ids) if uid]
        if not unique_ids:
            return set()

        if self._connected and self._client is not None:
            try:
                keys = [f"{_PRESENCE_PREFIX}{uid}" for uid in unique_ids]
                values = await self._client.mget(keys)
                return {
                    uid for uid, val in zip(unique_ids, values, strict=False) if val is not None
                }
            except (RedisError, OSError) as exc:
                self._warn_once(f"presence_mget_failed: {exc}")

        now = time.monotonic()
        online: set[str] = set()
        for uid in unique_ids:
            exp = self._mem_presence.get(uid)
            if exp is None:
                continue
            if exp <= now:
                self._mem_presence.pop(uid, None)
                continue
            online.add(uid)
        return online

    async def check_ws_rate_limit(
        self,
        user_id: str,
        *,
        limit: int = 20,
        window_seconds: int = 10,
    ) -> bool:
        """Sliding-window WebSocket event rate limit. Returns True when allowed."""
        key = f"{_RATE_LIMIT_PREFIX}{user_id}"
        now_wall = time.time()
        window_start = now_wall - window_seconds

        if self._connected and self._client is not None:
            try:
                member = f"{now_wall:.6f}:{secrets.token_hex(4)}"
                async with self._client.pipeline(transaction=True) as pipe:
                    pipe.zremrangebyscore(key, 0, window_start)
                    pipe.zcard(key)
                    pipe.zadd(key, {member: now_wall})
                    pipe.expire(key, window_seconds + 2)
                    results = await pipe.execute()
                current_count = int(results[1])
                if current_count >= limit:
                    # Undo the speculative entry so burst spam does not lock out forever.
                    await self._client.zrem(key, member)
                    return False
                return True
            except (RedisError, OSError) as exc:
                self._warn_once(f"rate_limit_failed: {exc}")

        now = time.monotonic()
        bucket = self._mem_rate.setdefault(user_id, deque())
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    async def check_chat_send_rate_limit(
        self,
        user_id: str,
        *,
        limit: int = 20,
        window_seconds: int = 10,
    ) -> bool:
        """Sliding-window per-user chat message send rate limit (20 msgs / 10s)."""
        key = f"{_CHAT_RATE_LIMIT_PREFIX}{user_id}"
        now_wall = time.time()
        window_start = now_wall - window_seconds

        if self._connected and self._client is not None:
            try:
                member = f"{now_wall:.6f}:{secrets.token_hex(4)}"
                async with self._client.pipeline(transaction=True) as pipe:
                    pipe.zremrangebyscore(key, 0, window_start)
                    pipe.zcard(key)
                    pipe.zadd(key, {member: now_wall})
                    pipe.expire(key, window_seconds + 2)
                    results = await pipe.execute()
                current_count = int(results[1])
                if current_count >= limit:
                    await self._client.zrem(key, member)
                    return False
                return True
            except (RedisError, OSError) as exc:
                self._warn_once(f"chat_rate_limit_failed: {exc}")

        now = time.monotonic()
        bucket = self._mem_chat_rate.setdefault(user_id, deque())
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    async def acquire_chat_notify_throttle(
        self,
        conversation_id: str,
        user_id: str,
        *,
        ttl_seconds: int = 300,
    ) -> bool:
        """Return True at most once per (conversation, user) per ``ttl_seconds``."""
        key = f"{_CHAT_NOTIFY_PREFIX}{conversation_id}:{user_id}"
        if self._connected and self._client is not None:
            try:
                acquired = await self._client.set(key, "1", ex=ttl_seconds, nx=True)
                return bool(acquired)
            except (RedisError, OSError) as exc:
                self._warn_once(f"chat_notify_throttle_failed: {exc}")

        now = time.monotonic()
        exp = self._mem_notify_throttle.get(key)
        if exp is not None and exp > now:
            return False
        self._mem_notify_throttle[key] = now + ttl_seconds
        return True

    async def get_str(self, key: str) -> str | None:
        if self._connected and self._client is not None:
            try:
                val = await self._client.get(key)
                return str(val) if val is not None else None
            except (RedisError, OSError) as exc:
                self._warn_once(f"kv_get_failed: {exc}")

        entry = self._mem_kv.get(key)
        if entry is None:
            return None
        exp, val = entry
        if exp <= time.monotonic():
            self._mem_kv.pop(key, None)
            return None
        return val

    async def set_str(self, key: str, value: str, *, ttl_seconds: int) -> None:
        if self._connected and self._client is not None:
            try:
                await self._client.set(key, value, ex=ttl_seconds)
                return
            except (RedisError, OSError) as exc:
                self._warn_once(f"kv_set_failed: {exc}")

        self._mem_kv[key] = (time.monotonic() + ttl_seconds, value)

    async def delete_key(self, key: str) -> None:
        if self._connected and self._client is not None:
            try:
                await self._client.delete(key)
            except (RedisError, OSError) as exc:
                self._warn_once(f"kv_delete_failed: {exc}")
        self._mem_kv.pop(key, None)

    async def get_json(self, key: str) -> Any | None:
        raw = await self.get_str(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        serialized = json.dumps(value, separators=(",", ":"), default=str)
        await self.set_str(key, serialized, ttl_seconds=ttl_seconds)

    async def incr_with_ttl(self, key: str, *, ttl_seconds: int) -> int:
        if self._connected and self._client is not None:
            try:
                async with self._client.pipeline(transaction=True) as pipe:
                    pipe.incr(key)
                    pipe.expire(key, ttl_seconds)
                    results = await pipe.execute()
                return int(results[0])
            except (RedisError, OSError) as exc:
                self._warn_once(f"kv_incr_failed: {exc}")

        now = time.monotonic()
        entry = self._mem_kv.get(key)
        current = 0
        if entry is not None and entry[0] > now:
            with contextlib.suppress(ValueError):
                current = int(entry[1])
        next_val = current + 1
        self._mem_kv[key] = (now + ttl_seconds, str(next_val))
        return next_val

    async def ttl_remaining(self, key: str) -> int:
        if self._connected and self._client is not None:
            try:
                remaining = int(await self._client.ttl(key))
                return max(remaining, 0)
            except (RedisError, OSError) as exc:
                self._warn_once(f"kv_ttl_failed: {exc}")

        entry = self._mem_kv.get(key)
        if entry is None:
            return 0
        rem = int(entry[0] - time.monotonic())
        if rem <= 0:
            self._mem_kv.pop(key, None)
            return 0
        return rem

    async def publish(self, channel: str, message: str) -> bool:
        """Publish to Redis Pub/Sub. Returns True if Redis accepted the publish."""
        if not self._connected or self._client is None:
            return False
        try:
            await self._client.publish(channel, message)
            return True
        except (RedisError, OSError) as exc:
            self._warn_once(f"publish_failed: {exc}")
            return False


redis_client = AsyncRedisClient()
