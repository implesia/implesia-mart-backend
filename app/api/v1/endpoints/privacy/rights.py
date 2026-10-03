from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.privacy.rights import RightsAdmin, RightsPublic, RightsWrite
from app.services.privacy import rights_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=RightsPublic)
async def read_privacy_rights(db: DbSession) -> RightsPublic:
    return await rights_service.public_view(db)


@admin_router.get("", response_model=RightsAdmin)
async def read_admin_privacy_rights(db: DbSession) -> RightsAdmin:
    return await rights_service.admin_view(db)


@admin_router.patch("", response_model=RightsAdmin)
async def update_privacy_rights(db: DbSession, payload: RightsWrite) -> RightsAdmin:
    return await rights_service.update_rights(db, payload)
