from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.site_header import HeaderAdmin, HeaderPublic, HeaderWrite
from app.services import site_header_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=HeaderPublic)
async def read_header(db: DbSession) -> HeaderPublic:
    """The storefront top menu. Served live from the database (no server cache), so an edit is
    visible on the next request. Falls back to the built-in menu when nothing is saved."""
    return await site_header_service.public_view(db)


@admin_router.get("", response_model=HeaderAdmin)
async def read_header_admin(db: DbSession) -> HeaderAdmin:
    return await site_header_service.admin_view(db)


@admin_router.put("", response_model=HeaderAdmin)
async def update_header(db: DbSession, payload: HeaderWrite) -> HeaderAdmin:
    return await site_header_service.update(db, payload)


@admin_router.delete("", response_model=HeaderAdmin)
async def reset_header(db: DbSession) -> HeaderAdmin:
    """Restore the built-in menu (removes the saved menu)."""
    return await site_header_service.reset(db)
