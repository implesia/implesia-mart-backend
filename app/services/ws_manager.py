"""Hardened WebSocket connection manager and ticket issuer.

CRITICAL MONOLITH RULE:
Never hold a PostgreSQL ``AsyncSession`` open inside the WebSocket lifecycle loop.
- Ticket issuance runs on a normal short-lived HTTP request (`POST /auth/ws-ticket` or
  `POST /customer/ws-ticket`) and stores a 30s single-use payload in Redis.
- WebSocket handshake (`WS /api/v1/ws?ticket=...`) consumes that ticket via Redis `GETDEL`
  with ZERO PostgreSQL queries.
- Heartbeats (`ping`/`pong`), presence TTL refresh, and `typing` relays touch Redis only
  (zero PostgreSQL queries).
- Conversation subscription (`subscribe_conversation`) runs a fast authorization check in
  a short-lived session (when needed) and closes it immediately before returning to the loop.
"""

from __future__ import annotations

import contextlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import PermissionDeniedError
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.user import User, UserRole
from app.schemas.auth import WSTicketResponse
from app.services import permission_service
from app.services.realtime_hub import (
    STAFF_COMMUNICATION_CHANNEL,
    STAFF_ORDERS_CHANNEL,
    conversation_channel,
    realtime_hub,
    user_channel,
)
from app.services.redis_client import redis_client

logger = get_logger(__name__)

MAX_CONNECTIONS_PER_USER = 5
MAX_FRAME_BYTES = 4096
IDLE_TIMEOUT_SECONDS = 60.0
WS_TICKET_TTL_SECONDS = 30
PRESENCE_TTL_SECONDS = 60
RATE_LIMIT_MAX_EVENTS = 20
RATE_LIMIT_WINDOW_SECONDS = 10

WS_CLOSE_IDLE_TIMEOUT = 4000
WS_CLOSE_AUTH_FAILED = 4001
WS_CLOSE_TOO_MANY_CONNECTIONS = 4008
WS_CLOSE_MESSAGE_TOO_BIG = 1009

ConversationAccessChecker = Callable[
    [AsyncSession, uuid.UUID, str, Literal["admin", "customer"], uuid.UUID],
    Awaitable[bool],
]


@dataclass(eq=False)
class WSConnection:
    websocket: WebSocket
    user_id: str
    role: str
    scope: Literal["admin", "customer"]
    channels: set[str] = field(default_factory=set)
    allowed_staff_channels: frozenset[str] = field(default_factory=frozenset)
    connected_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)


class WSConnectionManager:
    """Tracks active WebSocket connections on this worker and enforces scale guards."""

    def __init__(self) -> None:
        self.max_connections_per_user: int = MAX_CONNECTIONS_PER_USER
        self.max_frame_bytes: int = MAX_FRAME_BYTES
        self.idle_timeout_seconds: float = IDLE_TIMEOUT_SECONDS
        self.presence_ttl_seconds: int = PRESENCE_TTL_SECONDS
        self.rate_limit_max_events: int = RATE_LIMIT_MAX_EVENTS
        self.rate_limit_window_seconds: int = RATE_LIMIT_WINDOW_SECONDS
        self._session_factory: async_sessionmaker[AsyncSession] = SessionLocal
        self._conversation_access_checker: ConversationAccessChecker | None = None

        self._user_connections: dict[str, list[WSConnection]] = {}
        self._channel_connections: dict[str, set[WSConnection]] = {}
        realtime_hub.register_dispatcher(self.dispatch_channel)

    def set_session_factory(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = factory

    def set_conversation_access_checker(
        self, checker: ConversationAccessChecker | None
    ) -> None:
        """Allow messaging modules (Phase 19+) to plug in conversation ownership checks."""
        self._conversation_access_checker = checker

    def active_connection_count(self, user_id: str | None = None) -> int:
        if user_id is None:
            return sum(len(conns) for conns in self._user_connections.values())
        return len(self._user_connections.get(user_id, ()))

    def reset(self) -> None:
        """Clear local socket registries and restore default limits (used in tests)."""
        self._user_connections.clear()
        self._channel_connections.clear()
        self.max_connections_per_user = MAX_CONNECTIONS_PER_USER
        self.max_frame_bytes = MAX_FRAME_BYTES
        self.idle_timeout_seconds = IDLE_TIMEOUT_SECONDS
        self.presence_ttl_seconds = PRESENCE_TTL_SECONDS
        self.rate_limit_max_events = RATE_LIMIT_MAX_EVENTS
        self.rate_limit_window_seconds = RATE_LIMIT_WINDOW_SECONDS
        self._session_factory = SessionLocal
        self._conversation_access_checker = None

    async def compute_staff_channels(self, db: AsyncSession, user: User) -> list[str]:
        """Determine permitted realtime channels for a staff account via dynamic RBAC."""
        if not await permission_service.role_has_admin_access(db, user.role):
            raise PermissionDeniedError("Admin access is restricted to staff accounts")

        channels: list[str] = [user_channel(user.id)]
        perms = await permission_service.get_role_permissions_map(db, user.role)
        if permission_service.has_module_access(perms, "orders", "read"):
            channels.append(STAFF_ORDERS_CHANNEL)
        if (
            permission_service.has_module_access(perms, "inquiries", "read")
            or permission_service.has_module_access(perms, "reviews", "read")
            or permission_service.has_module_access(perms, "communication", "read")
        ):
            channels.append(STAFF_COMMUNICATION_CHANNEL)
        return channels

    async def issue_staff_ticket(self, db: AsyncSession, user: User) -> WSTicketResponse:
        channels = await self.compute_staff_channels(db, user)
        ticket = await redis_client.issue_ws_ticket(
            {
                "user_id": str(user.id),
                "role": str(user.role),
                "scope": "admin",
                "channels": channels,
            },
            ttl_seconds=WS_TICKET_TTL_SECONDS,
        )
        return WSTicketResponse(
            ticket=ticket,
            expires_in=WS_TICKET_TTL_SECONDS,
            scope="admin",
            channels=channels,
        )

    async def issue_customer_ticket(self, user: User) -> WSTicketResponse:
        channels = [user_channel(user.id)]
        ticket = await redis_client.issue_ws_ticket(
            {
                "user_id": str(user.id),
                "role": str(user.role),
                "scope": "customer",
                "channels": channels,
            },
            ttl_seconds=WS_TICKET_TTL_SECONDS,
        )
        return WSTicketResponse(
            ticket=ticket,
            expires_in=WS_TICKET_TTL_SECONDS,
            scope="customer",
            channels=channels,
        )

    async def accept_connection(
        self,
        websocket: WebSocket,
        ticket_payload: dict[str, Any],
    ) -> WSConnection | None:
        """Accept socket, enforce per-user cap (4008), subscribe channels, and set presence."""
        user_id = str(ticket_payload.get("user_id") or "").strip()
        role = str(ticket_payload.get("role") or "").strip()
        scope_raw = str(ticket_payload.get("scope") or "customer").strip()
        scope: Literal["admin", "customer"] = "admin" if scope_raw == "admin" else "customer"
        raw_channels = ticket_payload.get("channels")
        channel_list = (
            [str(ch) for ch in raw_channels if isinstance(ch, str) and ch.startswith("rt:")]
            if isinstance(raw_channels, list)
            else []
        )

        if not user_id:
            await websocket.accept()
            await websocket.close(code=WS_CLOSE_AUTH_FAILED, reason="Invalid ticket payload")
            return None

        await websocket.accept()

        existing = self._user_connections.get(user_id, [])
        if len(existing) >= self.max_connections_per_user:
            with contextlib.suppress(Exception):
                await websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "connection_limit",
                            "message": (
                                f"Maximum {self.max_connections_per_user} concurrent "
                                "connections per user reached"
                            ),
                        },
                    }
                )
            await websocket.close(
                code=WS_CLOSE_TOO_MANY_CONNECTIONS,
                reason="Too many concurrent connections",
            )
            logger.warning(
                "ws_connection_cap_rejected",
                user_id=user_id,
                active=len(existing),
                limit=self.max_connections_per_user,
            )
            return None

        personal = user_channel(user_id)
        initial_channels = {personal}
        staff_channels: set[str] = set()
        if scope == "admin":
            for ch in channel_list:
                if ch in {STAFF_ORDERS_CHANNEL, STAFF_COMMUNICATION_CHANNEL}:
                    initial_channels.add(ch)
                    staff_channels.add(ch)

        conn = WSConnection(
            websocket=websocket,
            user_id=user_id,
            role=role,
            scope=scope,
            channels=set(),
            allowed_staff_channels=frozenset(staff_channels),
        )
        was_offline = len(existing) == 0
        self._user_connections.setdefault(user_id, []).append(conn)
        for ch in initial_channels:
            self.subscribe(conn, ch)

        last_seen_iso = await redis_client.set_presence(
            user_id, ttl_seconds=self.presence_ttl_seconds
        )
        await websocket.send_json(
            {
                "type": "connected",
                "ts": datetime.now(UTC).isoformat(),
                "data": {
                    "user_id": user_id,
                    "scope": scope,
                    "channels": sorted(conn.channels),
                },
            }
        )
        if was_offline and scope != "admin":
            await realtime_hub.publish(
                STAFF_COMMUNICATION_CHANNEL,
                "presence.updated",
                {
                    "user_id": user_id,
                    "scope": scope,
                    "is_online": True,
                    "last_seen_at": last_seen_iso,
                },
            )
        return conn

    def subscribe(self, conn: WSConnection, channel: str) -> None:
        conn.channels.add(channel)
        self._channel_connections.setdefault(channel, set()).add(conn)

    def unsubscribe(self, conn: WSConnection, channel: str) -> None:
        conn.channels.discard(channel)
        subscribers = self._channel_connections.get(channel)
        if subscribers is not None:
            subscribers.discard(conn)
            if not subscribers:
                self._channel_connections.pop(channel, None)

    async def disconnect(self, conn: WSConnection) -> None:
        went_offline = False
        user_list = self._user_connections.get(conn.user_id)
        if user_list is not None:
            with contextlib.suppress(ValueError):
                user_list.remove(conn)
            if not user_list:
                self._user_connections.pop(conn.user_id, None)
                went_offline = True

        for ch in list(conn.channels):
            self.unsubscribe(conn, ch)

        if went_offline:
            last_seen_iso = await redis_client.clear_presence(conn.user_id)
            if conn.scope != "admin":
                await realtime_hub.publish(
                    STAFF_COMMUNICATION_CHANNEL,
                    "presence.updated",
                    {
                        "user_id": conn.user_id,
                        "scope": conn.scope,
                        "is_online": False,
                        "last_seen_at": last_seen_iso,
                    },
                )

    async def dispatch_channel(self, channel: str, envelope: dict[str, Any]) -> None:
        """Send an envelope to every local socket subscribed to ``channel``."""
        subscribers = list(self._channel_connections.get(channel, ()))
        if not subscribers:
            return

        data = envelope.get("data")
        is_internal = isinstance(data, dict) and bool(data.get("is_internal_note"))

        dead: list[WSConnection] = []
        for conn in subscribers:
            if is_internal and conn.scope != "admin":
                continue
            try:
                await conn.websocket.send_json(envelope)
            except Exception:  # noqa: BLE001
                dead.append(conn)

        for conn in dead:
            await self.disconnect(conn)

    async def _verify_conversation_access(
        self, conn: WSConnection, conversation_id: uuid.UUID
    ) -> bool:
        """Fast ownership/permission check using a short-lived DB session when required."""
        if conn.scope == "admin":
            if conn.role == UserRole.SUPERADMIN.value:
                return True
            if STAFF_COMMUNICATION_CHANNEL not in conn.allowed_staff_channels:
                return False
            if self._conversation_access_checker is None:
                return True

        try:
            user_uuid = uuid.UUID(conn.user_id)
        except ValueError:
            return False

        # Open a short-lived DB session strictly for this check and close immediately.
        async with self._session_factory() as db:
            if self._conversation_access_checker is not None:
                return await self._conversation_access_checker(
                    db, user_uuid, conn.role, conn.scope, conversation_id
                )
            user = await db.get(User, user_uuid)
            return user is not None and user.is_active

    async def handle_client_message(self, conn: WSConnection, raw_text: str) -> bool:
        """Process one incoming client text frame. Returns False when socket should close."""
        if len(raw_text.encode("utf-8")) > self.max_frame_bytes:
            with contextlib.suppress(Exception):
                await conn.websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "frame_too_large",
                            "message": f"Incoming frame exceeds {self.max_frame_bytes} bytes",
                        },
                    }
                )
            await conn.websocket.close(
                code=WS_CLOSE_MESSAGE_TOO_BIG,
                reason="Message exceeds 4 KB limit",
            )
            return False

        allowed = await redis_client.check_ws_rate_limit(
            conn.user_id,
            limit=self.rate_limit_max_events,
            window_seconds=self.rate_limit_window_seconds,
        )
        if not allowed:
            await conn.websocket.send_json(
                {
                    "type": "error",
                    "data": {
                        "code": "rate_limited",
                        "message": "Too many realtime events; slow down.",
                    },
                }
            )
            return True

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            await conn.websocket.send_json(
                {
                    "type": "error",
                    "data": {"code": "invalid_json", "message": "Frame must be valid JSON"},
                }
            )
            return True

        if not isinstance(payload, dict):
            await conn.websocket.send_json(
                {
                    "type": "error",
                    "data": {"code": "invalid_frame", "message": "Frame must be a JSON object"},
                }
            )
            return True

        conn.last_seen = time.monotonic()
        event_type = str(payload.get("type") or "").strip().lower()

        if event_type == "ping":
            await redis_client.set_presence(conn.user_id, ttl_seconds=self.presence_ttl_seconds)
            await conn.websocket.send_json(
                {"type": "pong", "ts": datetime.now(UTC).isoformat()}
            )
            return True

        if event_type == "typing":
            raw_conv_id = str(payload.get("conversation_id") or "").strip()
            try:
                conv_id = uuid.UUID(raw_conv_id)
            except ValueError:
                await conn.websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "invalid_conversation",
                            "message": "conversation_id must be a valid UUID",
                        },
                    }
                )
                return True

            channel = conversation_channel(conv_id)
            if (
                channel not in conn.channels
                and STAFF_COMMUNICATION_CHANNEL not in conn.allowed_staff_channels
            ):
                await conn.websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "not_subscribed",
                            "message": "Subscribe to the conversation before sending typing events",
                        },
                    }
                )
                return True

            # Ephemeral relay via Redis Pub/Sub only — ZERO DB write!
            await realtime_hub.publish(
                channel,
                "typing",
                {
                    "conversation_id": str(conv_id),
                    "user_id": conn.user_id,
                    "scope": conn.scope,
                    "is_typing": bool(payload.get("is_typing", True)),
                },
            )
            return True

        if event_type == "subscribe_conversation":
            raw_conv_id = str(payload.get("conversation_id") or "").strip()
            try:
                conv_id = uuid.UUID(raw_conv_id)
            except ValueError:
                await conn.websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "invalid_conversation",
                            "message": "conversation_id must be a valid UUID",
                        },
                    }
                )
                return True

            if not await self._verify_conversation_access(conn, conv_id):
                await conn.websocket.send_json(
                    {
                        "type": "error",
                        "data": {
                            "code": "forbidden",
                            "message": "Not permitted to subscribe to this conversation",
                        },
                    }
                )
                return True

            channel = conversation_channel(conv_id)
            self.subscribe(conn, channel)
            await conn.websocket.send_json(
                {
                    "type": "subscribed",
                    "data": {"conversation_id": str(conv_id), "channel": channel},
                }
            )
            return True

        if event_type == "unsubscribe_conversation":
            raw_conv_id = str(payload.get("conversation_id") or "").strip()
            try:
                conv_id = uuid.UUID(raw_conv_id)
            except ValueError:
                return True
            channel = conversation_channel(conv_id)
            self.unsubscribe(conn, channel)
            await conn.websocket.send_json(
                {
                    "type": "unsubscribed",
                    "data": {"conversation_id": str(conv_id), "channel": channel},
                }
            )
            return True

        await conn.websocket.send_json(
            {
                "type": "error",
                "data": {"code": "unknown_event", "message": f"Unsupported event: {event_type}"},
            }
        )
        return True


ws_manager = WSConnectionManager()
