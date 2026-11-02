import uuid

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.badge import BadgeAdminList, BadgeAdminRead, BadgeUpdate, BadgeWrite
from app.schemas.common import Message
from app.services import badge_service

router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@router.get("", response_model=BadgeAdminList)
async def list_badges(db: DbSession) -> BadgeAdminList:
    return await badge_service.admin_list(db)


@router.post("", response_model=BadgeAdminRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def create_badge(request: Request, db: DbSession, payload: BadgeWrite) -> BadgeAdminRead:
    del request
    badge = await badge_service.create(db, payload)
    return await badge_service.admin_read(db, badge)


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


@router.delete("/{badge_id}", response_model=Message)
@limiter.limit(settings.rate_limit_product_writes)
async def delete_badge(request: Request, db: DbSession, badge_id: uuid.UUID) -> Message:
    del request
    badge = await badge_service.get(db, badge_id)
    await badge_service.delete_badge(db, badge)
    return Message(message="Badge deleted")
