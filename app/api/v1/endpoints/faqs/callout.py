from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.faqs.callout import CalloutAdmin, CalloutPublic, CalloutWrite
from app.services.faqs import callout_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=CalloutPublic)
async def read_faq_callout(db: DbSession) -> CalloutPublic:
    return await callout_service.public_view(db)


@admin_router.get("", response_model=CalloutAdmin)
async def read_admin_faq_callout(db: DbSession) -> CalloutAdmin:
    return await callout_service.admin_view(db)


@admin_router.patch("", response_model=CalloutAdmin)
async def update_faq_callout(db: DbSession, payload: CalloutWrite) -> CalloutAdmin:
    return await callout_service.update_callout(db, payload)
