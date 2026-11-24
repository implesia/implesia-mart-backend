"""Customer-facing Direct Communication endpoints (Phase 19)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import CurrentUser, DbSession, no_store
from app.schemas.communication import (
    AttachmentUploadResponse,
    ConversationCreateRequest,
    ConversationRead,
    CustomerConversationListResponse,
    CustomerMessageCreateRequest,
    MarkReadResponse,
    MessageCursorPage,
    MessageRead,
)
from app.services import communication_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("/conversations", response_model=CustomerConversationListResponse)
async def list_customer_conversations(
    db: DbSession,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
) -> CustomerConversationListResponse:
    return await communication_service.list_customer_conversations(
        db,
        user,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/conversations",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_or_reuse_customer_conversation(
    db: DbSession,
    user: CurrentUser,
    payload: ConversationCreateRequest,
) -> ConversationRead:
    return await communication_service.start_or_reuse_customer_conversation(db, user, payload)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageCursorPage,
)
async def list_customer_conversation_messages(
    db: DbSession,
    user: CurrentUser,
    conversation_id: uuid.UUID,
    before_created_at: datetime | None = Query(None),
    before_id: uuid.UUID | None = Query(None),
    limit: int = Query(30, ge=1, le=50),
) -> MessageCursorPage:
    return await communication_service.list_customer_messages(
        db,
        user,
        conversation_id,
        before_created_at=before_created_at,
        before_id=before_id,
        limit=limit,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_customer_message(
    db: DbSession,
    user: CurrentUser,
    conversation_id: uuid.UUID,
    payload: CustomerMessageCreateRequest,
) -> MessageRead:
    return await communication_service.send_customer_message(
        db,
        user,
        conversation_id,
        payload,
    )


@router.post(
    "/conversations/{conversation_id}/attachment",
    response_model=AttachmentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_customer_conversation_attachment(
    db: DbSession,
    user: CurrentUser,
    conversation_id: uuid.UUID,
    file: UploadFile = File(...),
) -> AttachmentUploadResponse:
    url = await communication_service.upload_customer_attachment(db, user, conversation_id, file)
    return AttachmentUploadResponse(url=url)


@router.post(
    "/conversations/{conversation_id}/read",
    response_model=MarkReadResponse,
)
async def mark_customer_conversation_read(
    db: DbSession,
    user: CurrentUser,
    conversation_id: uuid.UUID,
) -> MarkReadResponse:
    return await communication_service.mark_customer_conversation_read(db, user, conversation_id)
