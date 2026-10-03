from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.faqs.help import HelpAdmin, HelpPublic, HelpWrite
from app.services.faqs import help_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=HelpPublic)
async def read_faq_help(db: DbSession) -> HelpPublic:
    return await help_service.public_view(db)


@admin_router.get("", response_model=HelpAdmin)
async def read_admin_faq_help(db: DbSession) -> HelpAdmin:
    return await help_service.admin_view(db)


@admin_router.patch("", response_model=HelpAdmin)
async def update_faq_help(db: DbSession, payload: HelpWrite) -> HelpAdmin:
    return await help_service.update_help(db, payload)
