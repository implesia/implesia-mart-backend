from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.api.deps import DbSession, no_store, require_module_for_method
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.home.popup import PopupAdmin, PopupImageUploaded, PopupPublic, PopupWrite
from app.services.home import popup_service

public_router = APIRouter()
admin_router = APIRouter(
    dependencies=[Depends(require_module_for_method("cms")), Depends(no_store)]
)


@public_router.get("", response_model=PopupPublic | None)
async def read_home_popup(db: DbSession) -> PopupPublic | None:
    """Active storefront popup configuration, or null when disabled."""
    return await popup_service.public_view(db)


@admin_router.get("", response_model=PopupAdmin)
async def read_popup(db: DbSession) -> PopupAdmin:
    return await popup_service.admin_view(db)


@admin_router.put("", response_model=PopupAdmin)
async def update_popup(db: DbSession, payload: PopupWrite) -> PopupAdmin:
    return await popup_service.update(db, payload)


@admin_router.post("/image", response_model=PopupImageUploaded, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def upload_popup_image(
    request: Request, image: Annotated[UploadFile, File()]
) -> PopupImageUploaded:
    """Upload a popup promotional image and return its `/media/popup/...` URL."""
    del request
    return PopupImageUploaded(url=await popup_service.upload_image(image))
