from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.site_footer import FooterAdmin, FooterPublic, FooterWrite, ImageUploaded
from app.services import site_footer_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=FooterPublic)
async def read_footer(db: DbSession) -> FooterPublic:
    """The storefront footer. Served live from the database (no server cache), so an edit is
    visible on the next request. Falls back to the built-in defaults when nothing is saved."""
    return await site_footer_service.public_view(db)


@admin_router.get("", response_model=FooterAdmin)
async def read_footer_admin(db: DbSession) -> FooterAdmin:
    return await site_footer_service.admin_view(db)


@admin_router.put("", response_model=FooterAdmin)
async def update_footer(db: DbSession, payload: FooterWrite) -> FooterAdmin:
    return await site_footer_service.update(db, payload)


@admin_router.delete("", response_model=FooterAdmin)
async def reset_footer(db: DbSession) -> FooterAdmin:
    """Restore the built-in defaults (removes the saved footer)."""
    return await site_footer_service.reset(db)


@admin_router.post("/logo", response_model=ImageUploaded, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def upload_footer_logo(
    request: Request, image: Annotated[UploadFile, File()]
) -> ImageUploaded:
    """Store one footer logo. Save the footer with the returned `url` as `logo_src`."""
    del request
    return ImageUploaded(url=await site_footer_service.upload_logo(image))
