from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.contact.form import FormAdmin, FormPublic, FormWrite
from app.services.contact import form_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=FormPublic)
async def read_contact_form(db: DbSession) -> FormPublic:
    return await form_service.public_view(db)


@admin_router.get("", response_model=FormAdmin)
async def read_admin_contact_form(db: DbSession) -> FormAdmin:
    return await form_service.admin_view(db)


@admin_router.patch("", response_model=FormAdmin)
async def update_contact_form(db: DbSession, payload: FormWrite) -> FormAdmin:
    return await form_service.update_form(db, payload)
