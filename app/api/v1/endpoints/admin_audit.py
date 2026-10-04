import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, RequireSuperadmin, no_store
from app.models.audit_event import AuditEvent
from app.schemas.audit import AuditEventRead
from app.schemas.common import Page, PaginationParams, page_count
from app.services import audit_service

router = APIRouter(dependencies=[Depends(no_store)])


def _read(row: AuditEvent) -> AuditEventRead:
    return AuditEventRead(
        id=row.id,
        actor_user_id=row.actor_user_id,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        created_at=row.created_at,
        metadata=dict(row.event_metadata),
    )


@router.get("", response_model=Page[AuditEventRead])
async def list_audit_events(
    _: RequireSuperadmin,
    db: DbSession,
    pagination: Annotated[PaginationParams, Depends()],
    action: Annotated[str | None, Query()] = None,
    target_type: Annotated[str | None, Query()] = None,
    target_id: Annotated[str | None, Query()] = None,
    actor_user_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[AuditEventRead]:
    rows, total = await audit_service.list_events(
        db,
        pagination.offset,
        pagination.page_size,
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_user_id=actor_user_id,
    )
    return Page[AuditEventRead](
        items=[_read(row) for row in rows],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        pages=page_count(total, pagination.page_size),
    )
