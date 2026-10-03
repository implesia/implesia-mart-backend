from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.privacy.sharing import SharingAdmin, SharingPublic, SharingWrite
from app.services.privacy import sharing_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=SharingPublic)
async def read_privacy_sharing(db: DbSession) -> SharingPublic:
    return await sharing_service.public_view(db)


@admin_router.get("", response_model=SharingAdmin)
async def read_admin_privacy_sharing(db: DbSession) -> SharingAdmin:
    return await sharing_service.admin_view(db)


@admin_router.patch("", response_model=SharingAdmin)
async def update_privacy_sharing(db: DbSession, payload: SharingWrite) -> SharingAdmin:
    return await sharing_service.update_sharing(db, payload)
