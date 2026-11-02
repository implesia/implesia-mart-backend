from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.home.media import MediaAdmin, MediaPublic, MediaUploaded, MediaWrite
from app.services.home import media_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=MediaPublic | None, dependencies=[Depends(no_store)])
async def read_home_media(db: DbSession) -> MediaPublic | None:
    """The live media section, or null when none is published."""
    return await media_service.public_view(db)


@admin_router.get("", response_model=MediaAdmin)
async def read_media(db: DbSession) -> MediaAdmin:
    return await media_service.admin_view(db)


@admin_router.put("", response_model=MediaAdmin)
async def update_media(db: DbSession, payload: MediaWrite) -> MediaAdmin:
    return await media_service.update(db, payload)


@admin_router.post("/image", response_model=MediaUploaded, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def upload_media_image(
    request: Request, image: Annotated[UploadFile, File()]
) -> MediaUploaded:
    """Store one image (the section image or a video/YouTube thumbnail). Save with its `url`."""
    del request
    return MediaUploaded(url=await media_service.upload_image(image))


@admin_router.post("/video", response_model=MediaUploaded, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def upload_media_video(
    request: Request, video: Annotated[UploadFile, File()]
) -> MediaUploaded:
    """Store one MP4/WEBM video (50 MB max). Save the section with its `url` as `video_src`."""
    del request
    return MediaUploaded(url=await media_service.upload_video(video))
