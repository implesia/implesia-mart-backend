"""Inbound courier webhook endpoints (Phase 24)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header

from app.api.deps import DbSession, no_store
from app.schemas.courier import SteadfastWebhookResponse
from app.services.courier import steadfast_webhook_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.post("/steadfast", response_model=SteadfastWebhookResponse)
async def receive_steadfast_webhook(
    db: DbSession,
    background: BackgroundTasks,
    payload: dict[str, Any] = Body(...),
    authorization: str | None = Header(default=None),
    x_steadfast_webhook_secret: str | None = Header(default=None),
    x_webhook_secret: str | None = Header(default=None),
    x_steadfast_token: str | None = Header(default=None),
) -> SteadfastWebhookResponse:
    steadfast_webhook_service.verify_webhook_secret(
        authorization=authorization,
        header_tokens=(
            x_steadfast_webhook_secret,
            x_webhook_secret,
            x_steadfast_token,
        ),
    )
    return await steadfast_webhook_service.process_steadfast_webhook(
        db,
        payload,
        background=background,
    )
