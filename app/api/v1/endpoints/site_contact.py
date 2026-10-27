from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.site_contact import SiteContactAdmin, SiteContactPublic, SiteContactWrite
from app.services import site_contact_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=SiteContactPublic)
async def read_contact(db: DbSession) -> SiteContactPublic:
    """The store's phone, WhatsApp and email. Served live from the database (no server
    cache), so an edit is visible on the next request."""
    return await site_contact_service.public_view(db)


@admin_router.get("", response_model=SiteContactAdmin)
async def read_contact_admin(db: DbSession) -> SiteContactAdmin:
    return await site_contact_service.admin_view(db)


@admin_router.put("", response_model=SiteContactAdmin)
async def update_contact(db: DbSession, payload: SiteContactWrite) -> SiteContactAdmin:
    return await site_contact_service.update(db, payload)
