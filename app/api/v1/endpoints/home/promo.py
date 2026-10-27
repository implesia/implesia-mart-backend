from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.home.promo import ImageUploaded, PromoAdmin, PromoPublic, PromoWrite
from app.services.home import promo_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=PromoPublic | None)
async def read_home_promo(db: DbSession) -> PromoPublic | None:
    """The live promotional banner, or null when none is published."""
    return await promo_service.public_view(db)


@admin_router.get("", response_model=PromoAdmin)
async def read_promo(db: DbSession) -> PromoAdmin:
    return await promo_service.admin_view(db)


@admin_router.put("", response_model=PromoAdmin)
async def update_promo(db: DbSession, payload: PromoWrite) -> PromoAdmin:
    return await promo_service.update(db, payload)


@admin_router.post("/image", response_model=ImageUploaded, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def upload_promo_image(
    request: Request, image: Annotated[UploadFile, File()]
) -> ImageUploaded:
    """Store one banner image. Save the banner with the returned `url` as `image_src`."""
    del request
    return ImageUploaded(url=await promo_service.upload_image(image))
