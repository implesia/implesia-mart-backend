from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.contact.faq import FaqAdmin, FaqPublic, FaqWrite
from app.services.contact import faq_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=FaqPublic)
async def read_contact_faq(db: DbSession) -> FaqPublic:
    return await faq_service.public_view(db)


@admin_router.get("", response_model=FaqAdmin)
async def read_admin_contact_faq(db: DbSession) -> FaqAdmin:
    return await faq_service.admin_view(db)


@admin_router.patch("", response_model=FaqAdmin)
async def update_contact_faq(db: DbSession, payload: FaqWrite) -> FaqAdmin:
    return await faq_service.update_faq(db, payload)
