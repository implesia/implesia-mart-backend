"""Dropshipper Storefront Builder endpoints (/api/v1/dropshipper/store/*)."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.deps import DbSession, RequireApprovedDropshipper, no_store
from app.schemas.dropshipper_store import (
    DropshipperStoreMediaUploadResponse,
    DropshipperStoreProductImportRequest,
    DropshipperStoreProductListResponse,
    DropshipperStoreProductRead,
    DropshipperStoreProductUpdate,
    DropshipperStoreRead,
    DropshipperStoreSeoTrackingUpdate,
    DropshipperStoreUpdate,
)
from app.services import dropshipper_store_service, image_storage

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("/store", response_model=DropshipperStoreRead)
async def get_dropshipper_store(
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipperStoreRead:
    return await dropshipper_store_service.get_my_store(db, user)


@router.patch("/store", response_model=DropshipperStoreRead)
async def update_dropshipper_store(
    payload: DropshipperStoreUpdate,
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipperStoreRead:
    return await dropshipper_store_service.update_my_store(db, user, payload)


@router.patch("/store/seo-tracking", response_model=DropshipperStoreRead)
async def update_dropshipper_store_seo_tracking(
    payload: DropshipperStoreSeoTrackingUpdate,
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipperStoreRead:
    return await dropshipper_store_service.update_my_store_seo_tracking(db, user, payload)


@router.post("/store/media", response_model=DropshipperStoreMediaUploadResponse)
async def upload_dropshipper_store_media(
    user: RequireApprovedDropshipper,
    file: UploadFile = File(...),
    field: Literal["hero_banner", "mobile_banner", "logo", "favicon", "og_image"] = Form(
        "hero_banner"
    ),
) -> DropshipperStoreMediaUploadResponse:
    _ = user
    data = await image_storage.read_image(file)
    url = image_storage.store_image(data, folder="dropshippers")
    return DropshipperStoreMediaUploadResponse(url=url, field=field)


@router.get("/store/products", response_model=DropshipperStoreProductListResponse)
async def list_dropshipper_store_products(
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipperStoreProductListResponse:
    return await dropshipper_store_service.list_my_store_products(db, user)


@router.post(
    "/store/products",
    response_model=DropshipperStoreProductListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_dropshipper_store_products(
    payload: DropshipperStoreProductImportRequest,
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipperStoreProductListResponse:
    return await dropshipper_store_service.import_my_store_products(db, user, payload)


@router.patch("/store/products/{store_product_id}", response_model=DropshipperStoreProductRead)
async def update_dropshipper_store_product(
    store_product_id: uuid.UUID,
    payload: DropshipperStoreProductUpdate,
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipperStoreProductRead:
    return await dropshipper_store_service.update_my_store_product(
        db, user, store_product_id, payload
    )


@router.delete("/store/products/{store_product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dropshipper_store_product(
    store_product_id: uuid.UUID,
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> None:
    await dropshipper_store_service.delete_my_store_product(db, user, store_product_id)
