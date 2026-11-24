"""Admin / Staff Direct Communication endpoints (Phase 19, protected by dynamic RBAC)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import DbSession, no_store, require_module_access
from app.models.user import User
from app.schemas.common import Page
from app.schemas.communication import (
    AdminCommunicationSummaryResponse,
    AdminConversationDetailRead,
    AdminConversationUpdateRequest,
    AdminMessageCreateRequest,
    AttachmentUploadResponse,
    ConversationRead,
    ConversationStatusLiteral,
    ConversationTypeLiteral,
    MarkReadResponse,
    MessageCursorPage,
    MessageRead,
)
from app.services import communication_service

router = APIRouter(dependencies=[Depends(no_store)])

RequireCommRead = Annotated[User, Depends(require_module_access("communication", "read"))]
RequireCommWrite = Annotated[User, Depends(require_module_access("communication", "write"))]


@router.get("/summary", response_model=AdminCommunicationSummaryResponse)
async def get_communication_summary(
    db: DbSession,
    staff: RequireCommRead,
) -> AdminCommunicationSummaryResponse:
    return await communication_service.get_admin_summary(db, staff)


@router.get("/conversations", response_model=Page[ConversationRead])
async def list_admin_conversations(
    db: DbSession,
    staff: RequireCommRead,
    conv_type: ConversationTypeLiteral | None = Query(None, alias="type"),
    conv_status: ConversationStatusLiteral | None = Query(None, alias="status"),
    assigned: str | None = Query(None),
    assigned_staff_id: uuid.UUID | None = Query(None),
    q: str | None = Query(None, max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
) -> Page[ConversationRead]:
    return await communication_service.list_admin_conversations(
        db,
        staff,
        conv_type=conv_type,
        status=conv_status,
        assigned=assigned,
        assigned_staff_id=assigned_staff_id,
        q=q,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=AdminConversationDetailRead,
)
async def get_admin_conversation_detail(
    db: DbSession,
    staff: RequireCommRead,
    conversation_id: uuid.UUID,
) -> AdminConversationDetailRead:
    return await communication_service.get_admin_conversation_detail(db, staff, conversation_id)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageCursorPage,
)
async def list_admin_conversation_messages(
    db: DbSession,
    _staff: RequireCommRead,
    conversation_id: uuid.UUID,
    before_created_at: datetime | None = Query(None),
    before_id: uuid.UUID | None = Query(None),
    limit: int = Query(30, ge=1, le=50),
) -> MessageCursorPage:
    return await communication_service.list_admin_messages(
        db,
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
async def post_admin_message(
    db: DbSession,
    staff: RequireCommWrite,
    conversation_id: uuid.UUID,
    payload: AdminMessageCreateRequest,
) -> MessageRead:
    return await communication_service.send_admin_message(db, staff, conversation_id, payload)


@router.post(
    "/conversations/{conversation_id}/attachment",
    response_model=AttachmentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_admin_conversation_attachment(
    db: DbSession,
    _staff: RequireCommWrite,
    conversation_id: uuid.UUID,
    file: UploadFile = File(...),
) -> AttachmentUploadResponse:
    url = await communication_service.upload_admin_attachment(db, conversation_id, file)
    return AttachmentUploadResponse(url=url)


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationRead,
)
async def update_admin_conversation(
    db: DbSession,
    staff: RequireCommWrite,
    conversation_id: uuid.UUID,
    payload: AdminConversationUpdateRequest,
) -> ConversationRead:
    return await communication_service.update_admin_conversation(
        db,
        staff,
        conversation_id,
        payload,
    )


@router.post(
    "/conversations/{conversation_id}/read",
    response_model=MarkReadResponse,
)
async def mark_admin_conversation_read(
    db: DbSession,
    staff: RequireCommRead,
    conversation_id: uuid.UUID,
) -> MarkReadResponse:
    return await communication_service.mark_admin_conversation_read(db, staff, conversation_id)
