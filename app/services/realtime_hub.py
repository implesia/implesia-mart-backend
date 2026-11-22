"""Redis Pub/Sub + in-process fallback realtime hub for multi-worker event fan-out.

Channel conventions (all matched by pattern ``rt:*``):
- ``rt:user:{user_id}`` — personal user events (notifications, unread count, direct messages)
- ``rt:staff:orders`` — staff live order alerts (requires ``orders`` read permission)
- ``rt:staff:communication`` — staff live inbox/chat/typing events
- ``rt:conv:{conversation_id}`` — conversation-scoped messages & ephemeral typing indicators
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError

from app.core.logging import get_logger
from app.services.redis_client import redis_client

logger = get_logger(__name__)

RT_CHANNEL_PATTERN = "rt:*"
STAFF_ORDERS_CHANNEL = "rt:staff:orders"
STAFF_COMMUNICATION_CHANNEL = "rt:staff:communication"

ChannelDispatcher = Callable[[str, dict[str, Any]], Awaitable[None]]


def user_channel(user_id: uuid.UUID | str) -> str:
    return f"rt:user:{user_id}"


def conversation_channel(conversation_id: uuid.UUID | str) -> str:
    return f"rt:conv:{conversation_id}"


class RealtimeHub:
    """Single background subscriber per worker with transparent in-process fallback."""

    def __init__(self) -> None:
        self._subscriber_task: asyncio.Task[None] | None = None
        self._redis_listening: bool = False
        self._running: bool = False
        self._dispatchers: list[ChannelDispatcher] = []

    def register_dispatcher(self, dispatcher: ChannelDispatcher) -> None:
        if dispatcher not in self._dispatchers:
            self._dispatchers.append(dispatcher)

    def unregister_dispatcher(self, dispatcher: ChannelDispatcher) -> None:
        with contextlib.suppress(ValueError):
            self._dispatchers.remove(dispatcher)

    @property
    def is_redis_pubsub_active(self) -> bool:
        return self._redis_listening and redis_client.is_redis_available

    async def start(self) -> None:
        """Start the single worker Pub/Sub listener task (gracefully degrades if Redis is down)."""
        if self._running:
            return
        self._running = True
        connected = await redis_client.connect()
        if not connected:
            self._redis_listening = False
            logger.info("realtime_hub_started", transport="in_process")
            return

        self._subscriber_task = asyncio.create_task(
            self._subscriber_loop(),
            name="realtime-redis-pubsub",
        )
        logger.info("realtime_hub_started", transport="redis_pubsub", pattern=RT_CHANNEL_PATTERN)

    async def stop(self) -> None:
        self._running = False
        self._redis_listening = False
        if self._subscriber_task is not None:
            self._subscriber_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._subscriber_task
            self._subscriber_task = None
        logger.info("realtime_hub_stopped")

    async def _subscriber_loop(self) -> None:
        backoff = 1.0
        while self._running:
            client = redis_client.raw_client()
            if client is None:
                self._redis_listening = False
                await asyncio.sleep(min(backoff, 10.0))
                backoff = min(backoff * 2.0, 10.0)
                await redis_client.connect()
                continue

            pubsub = client.pubsub(ignore_subscribe_messages=True)
            try:
                await pubsub.psubscribe(RT_CHANNEL_PATTERN)
                self._redis_listening = True
                backoff = 1.0
                while self._running:
                    message = await pubsub.get_message(timeout=1.0)
                    if message is None:
                        continue
                    if message.get("type") != "pmessage":
                        continue
                    channel = str(message.get("channel") or "")
                    raw_data = message.get("data")
                    if not channel or not isinstance(raw_data, str):
                        continue
                    try:
                        envelope = json.loads(raw_data)
                    except json.JSONDecodeError:
                        logger.warning("realtime_invalid_json", channel=channel)
                        continue
                    if isinstance(envelope, dict):
                        await self.dispatch_local(channel, envelope)
            except asyncio.CancelledError:
                raise
            except (RedisError, OSError) as exc:
                self._redis_listening = False
                logger.warning("realtime_pubsub_disconnected", error=str(exc), retry_in=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 15.0)
            finally:
                self._redis_listening = False
                with contextlib.suppress(Exception):
                    await pubsub.punsubscribe(RT_CHANNEL_PATTERN)
                with contextlib.suppress(Exception):
                    await pubsub.aclose()

    async def dispatch_local(self, channel: str, envelope: dict[str, Any]) -> None:
        """Deliver an envelope to every registered local dispatcher without raising."""
        for dispatcher in list(self._dispatchers):
            try:
                await dispatcher(channel, envelope)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "realtime_dispatch_error",
                    channel=channel,
                    event_type=envelope.get("type"),
                    error=str(exc),
                )

    async def publish(
        self,
        channel: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Publish a real-time JSON envelope. Non-blocking / failure-safe for callers."""
        envelope: dict[str, Any] = {
            "type": event_type,
            "channel": channel,
            "ts": datetime.now(UTC).isoformat(),
            "data": data,
        }
        try:
            if self.is_redis_pubsub_active:
                serialized = json.dumps(envelope, separators=(",", ":"), default=str)
                published = await redis_client.publish(channel, serialized)
                if published:
                    return
            await self.dispatch_local(channel, envelope)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "realtime_publish_failed",
                channel=channel,
                event_type=event_type,
                error=str(exc),
            )


realtime_hub = RealtimeHub()
