import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request, status

from app.api.deps import DbSession, no_store, require_module_access, require_module_for_method
from app.core.config import settings
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.badge import (
    BadgeAdminList,
    BadgeAdminRead,
    BadgeDeleteImpact,
    BadgeDeleteRequest,
    BadgeDeleteResult,
    BadgeUpdate,
    BadgeWrite,
)
from app.services import badge_service

_AuditDeleteFull = Annotated[User, Depends(require_module_access("audit_deletes", "full"))]

router = APIRouter(dependencies=[Depends(require_module_for_method("products")), Depends(no_store)])


@router.get("", response_model=BadgeAdminList)
async def list_badges(db: DbSession) -> BadgeAdminList:
    return await badge_service.admin_list(db)


@router.post("", response_model=BadgeAdminRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def create_badge(request: Request, db: DbSession, payload: BadgeWrite) -> BadgeAdminRead:
    del request
    badge = await badge_service.create(db, payload)
    return await badge_service.admin_read(db, badge)


@router.get("/{badge_id}/delete-impact", response_model=BadgeDeleteImpact)
async def badge_delete_impact(
    db: DbSession,
    actor: _AuditDeleteFull,
    badge_id: uuid.UUID,
) -> BadgeDeleteImpact:
    del actor
    return await badge_service.delete_impact(db, badge_id)


@router.get("/{badge_id}", response_model=BadgeAdminRead)
async def get_badge(db: DbSession, badge_id: uuid.UUID) -> BadgeAdminRead:
    return await badge_service.admin_read(db, await badge_service.get(db, badge_id))


@router.patch("/{badge_id}", response_model=BadgeAdminRead)
@limiter.limit(settings.rate_limit_product_writes)
async def update_badge(
    request: Request, db: DbSession, badge_id: uuid.UUID, payload: BadgeUpdate
) -> BadgeAdminRead:
    del request
    badge = await badge_service.get(db, badge_id)
    await badge_service.update(db, badge, payload)
    return await badge_service.admin_read(db, badge)


@router.delete("/{badge_id}", response_model=BadgeDeleteResult)
@limiter.limit(settings.rate_limit_product_writes)
async def delete_badge(
    request: Request,
    db: DbSession,
    actor: _AuditDeleteFull,
    badge_id: uuid.UUID,
    payload: BadgeDeleteRequest | None = Body(default=None),
) -> BadgeDeleteResult:
    del request
    badge = await badge_service.get(db, badge_id)
    return await badge_service.delete_badge(db, badge, payload=payload, actor=actor)
