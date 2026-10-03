from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.privacy.usage import UsageAdmin, UsagePublic, UsageWrite
from app.services.privacy import usage_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=UsagePublic)
async def read_privacy_usage(db: DbSession) -> UsagePublic:
    return await usage_service.public_view(db)


@admin_router.get("", response_model=UsageAdmin)
async def read_admin_privacy_usage(db: DbSession) -> UsageAdmin:
    return await usage_service.admin_view(db)


@admin_router.patch("", response_model=UsageAdmin)
async def update_privacy_usage(db: DbSession, payload: UsageWrite) -> UsageAdmin:
    return await usage_service.update_usage(db, payload)
