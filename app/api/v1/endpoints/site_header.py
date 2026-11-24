from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.api.deps import DbSession, no_store, require_module_for_method
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.site_footer import ImageUploaded
from app.schemas.site_header import HeaderAdmin, HeaderPublic, HeaderWrite
from app.services import site_header_service

public_router = APIRouter()
admin_router = APIRouter(
    dependencies=[Depends(require_module_for_method("cms")), Depends(no_store)]
)


@public_router.get("", response_model=HeaderPublic)
async def read_header(db: DbSession) -> HeaderPublic:
    """The storefront top menu and logo. Served live from the database (no server cache), so an
    edit is visible on the next request. Falls back to the built-in menu and logo when nothing
    is saved."""
    return await site_header_service.public_view(db)


@admin_router.get("", response_model=HeaderAdmin)
async def read_header_admin(db: DbSession) -> HeaderAdmin:
    return await site_header_service.admin_view(db)


@admin_router.put("", response_model=HeaderAdmin)
async def update_header(db: DbSession, payload: HeaderWrite) -> HeaderAdmin:
    return await site_header_service.update(db, payload)


@admin_router.delete("", response_model=HeaderAdmin)
async def reset_header(db: DbSession) -> HeaderAdmin:
    """Restore the built-in menu and logo (removes the saved header)."""
    return await site_header_service.reset(db)


@admin_router.post("/logo", response_model=ImageUploaded, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def upload_header_logo(
    request: Request, image: Annotated[UploadFile, File()]
) -> ImageUploaded:
    """Store one navbar logo. Save the header with the returned `url` as `logo_src`."""
    del request
    return ImageUploaded(url=await site_header_service.upload_logo(image))
