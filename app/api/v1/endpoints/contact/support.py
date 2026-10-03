from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.contact.support import SupportAdmin, SupportPublic, SupportWrite
from app.services.contact import support_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=SupportPublic)
async def read_contact_support(db: DbSession) -> SupportPublic:
    return await support_service.public_view(db)


@admin_router.get("", response_model=SupportAdmin)
async def read_admin_contact_support(db: DbSession) -> SupportAdmin:
    return await support_service.admin_view(db)


@admin_router.patch("", response_model=SupportAdmin)
async def update_contact_support(db: DbSession, payload: SupportWrite) -> SupportAdmin:
    return await support_service.update_support(db, payload)
