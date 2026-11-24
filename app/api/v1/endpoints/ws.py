"""WebSocket endpoint (`WS /api/v1/ws?ticket=...`).

Zero PostgreSQL ``AsyncSession`` dependency is injected into the WebSocket handler so
long-lived connections NEVER hold database pool connections open.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.services.redis_client import redis_client
from app.services.ws_manager import (
    WS_CLOSE_AUTH_FAILED,
    WS_CLOSE_IDLE_TIMEOUT,
    ws_manager,
)

logger = get_logger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    ticket: str | None = Query(default=None),
) -> None:
    """Authenticate via single-use 30s Redis ticket and enter zero-DB-hold event loop."""
    if not ticket:
        await websocket.accept()
        await websocket.close(code=WS_CLOSE_AUTH_FAILED, reason="Missing WebSocket ticket")
        return

    ticket_payload = await redis_client.consume_ws_ticket(ticket)
    if ticket_payload is None:
        await websocket.accept()
        await websocket.close(
            code=WS_CLOSE_AUTH_FAILED,
            reason="Invalid, expired, or already used WebSocket ticket",
        )
        return

    conn = await ws_manager.accept_connection(websocket, ticket_payload)
    if conn is None:
        return

    try:
        while True:
            try:
                raw_text = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=ws_manager.idle_timeout_seconds,
                )
            except TimeoutError:
                with contextlib.suppress(Exception):
                    await websocket.close(
                        code=WS_CLOSE_IDLE_TIMEOUT,
                        reason="Idle heartbeat timeout",
                    )
                break

            keep_open = await ws_manager.handle_client_message(conn, raw_text)
            if not keep_open:
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws_loop_error", user_id=conn.user_id, error=str(exc))
    finally:
        await ws_manager.disconnect(conn)
