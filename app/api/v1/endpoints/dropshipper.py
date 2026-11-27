"""Dropshipper partner endpoints (/api/v1/dropshipper/*)."""

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.deps import CurrentUser, DbSession, RequireApprovedDropshipper, no_store
from app.schemas.dropshipping import (
    DropshipperApplyRequest,
    DropshipperCatalogResponse,
    DropshipperMeResponse,
    DropshipperProfileRead,
    DropshipperProfileUpdate,
    DropshipperUploadResponse,
)
from app.services import dropshipping_service, image_storage

router = APIRouter(dependencies=[Depends(no_store)])


@router.post("/apply", response_model=DropshipperProfileRead, status_code=status.HTTP_201_CREATED)
async def apply_dropshipper(
    payload: DropshipperApplyRequest,
    db: DbSession,
    user: CurrentUser,
) -> DropshipperProfileRead:
    return await dropshipping_service.apply_dropshipper(db, user, payload)


@router.get("/me", response_model=DropshipperMeResponse)
async def get_dropshipper_me(
    db: DbSession,
    user: CurrentUser,
) -> DropshipperMeResponse:
    return await dropshipping_service.get_me(db, user)


@router.patch("/profile", response_model=DropshipperProfileRead)
async def update_dropshipper_profile(
    payload: DropshipperProfileUpdate,
    db: DbSession,
    user: CurrentUser,
) -> DropshipperProfileRead:
    return await dropshipping_service.update_profile(db, user, payload)


@router.post("/profile/upload", response_model=DropshipperUploadResponse)
async def upload_dropshipper_asset(
    user: CurrentUser,
    file: UploadFile = File(...),
    field: Literal["shop_logo", "nid_front", "nid_back"] = Form("shop_logo"),
) -> DropshipperUploadResponse:
    _ = user
    data = await image_storage.read_image(file)
    url = image_storage.store_image(data, folder="dropshippers")
    return DropshipperUploadResponse(url=url, field=field)


@router.get("/catalog", response_model=DropshipperCatalogResponse)
async def get_dropshipper_catalog(
    db: DbSession,
    user: RequireApprovedDropshipper,
    q: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=80),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=60),
) -> DropshipperCatalogResponse:
    _ = user
    return await dropshipping_service.list_catalog(
        db, q=q, category=category, page=page, page_size=page_size
    )
