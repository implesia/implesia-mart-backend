import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, require_editor
from app.schemas.common import Message, Page, PaginationParams
from app.schemas.home.banner import (
    BannerSlideAdmin,
    BannerSlideUpdate,
    BannerSlideWrite,
    HomeBannerPublic,
    HomeBannerRead,
    HomeBannerUpdate,
)
from app.services.home import banner_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor)])


@public_router.get("", response_model=HomeBannerPublic)
async def read_home_banner(db: DbSession) -> HomeBannerPublic:
    return await banner_service.public_banner(db)


@admin_router.get("", response_model=HomeBannerRead)
async def read_banner_settings(db: DbSession) -> HomeBannerRead:
    banner = await banner_service.ensure_banner(db)
    return HomeBannerRead.model_validate(banner)


@admin_router.patch("", response_model=HomeBannerRead)
async def update_banner_settings(db: DbSession, payload: HomeBannerUpdate) -> HomeBannerRead:
    banner = await banner_service.ensure_banner(db)
    updated = await banner_service.update_banner(db, banner, payload)
    return HomeBannerRead.model_validate(updated)


@admin_router.get("/slides", response_model=Page[BannerSlideAdmin])
async def list_banner_slides(
    db: DbSession,
    pagination: Annotated[PaginationParams, Depends()],
) -> Page[BannerSlideAdmin]:
    banner = await banner_service.ensure_banner(db)
    slides, total = await banner_service.list_slides(
        db, banner.id, pagination.offset, pagination.page_size
    )
    lead_id = await banner_service.priority_slide_id(db, banner.id)
    return Page[BannerSlideAdmin](
        items=[
            banner_service.present_admin_slide(slide, image_priority=slide.id == lead_id)
            for slide in slides
        ],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@admin_router.post("/slides", response_model=BannerSlideAdmin, status_code=status.HTTP_201_CREATED)
async def create_banner_slide(db: DbSession, payload: BannerSlideWrite) -> BannerSlideAdmin:
    banner = await banner_service.ensure_banner(db)
    slide = await banner_service.create_slide(db, banner, payload)
    return banner_service.present_admin_slide(
        slide, image_priority=await banner_service.is_priority_slide(db, slide)
    )


@admin_router.get("/slides/{slide_id}", response_model=BannerSlideAdmin)
async def read_banner_slide(db: DbSession, slide_id: uuid.UUID) -> BannerSlideAdmin:
    slide = await banner_service.get_slide(db, slide_id)
    return banner_service.present_admin_slide(
        slide, image_priority=await banner_service.is_priority_slide(db, slide)
    )


@admin_router.patch("/slides/{slide_id}", response_model=BannerSlideAdmin)
async def update_banner_slide(
    db: DbSession, slide_id: uuid.UUID, payload: BannerSlideUpdate
) -> BannerSlideAdmin:
    slide = await banner_service.get_slide(db, slide_id)
    updated = await banner_service.update_slide(db, slide, payload)
    return banner_service.present_admin_slide(
        updated, image_priority=await banner_service.is_priority_slide(db, updated)
    )


@admin_router.delete("/slides/{slide_id}", response_model=Message)
async def delete_banner_slide(db: DbSession, slide_id: uuid.UUID) -> Message:
    slide = await banner_service.get_slide(db, slide_id)
    await banner_service.delete_slide(db, slide)
    return Message(message="Banner slide deleted")
