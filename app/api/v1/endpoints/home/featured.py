import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.common import Message
from app.schemas.home.featured import (
    FeaturedAdmin,
    FeaturedCopyUpdate,
    FeaturedItemRead,
    FeaturedItemWrite,
    FeaturedPublic,
    FeaturedReorder,
)
from app.services.home import featured_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=FeaturedPublic)
async def read_home_featured(db: DbSession) -> FeaturedPublic:
    return await featured_service.public_view(db)


@admin_router.get("", response_model=FeaturedAdmin)
async def list_featured(db: DbSession) -> FeaturedAdmin:
    return await featured_service.admin_view(db)


@admin_router.patch("", response_model=FeaturedAdmin)
async def update_featured_copy(db: DbSession, payload: FeaturedCopyUpdate) -> FeaturedAdmin:
    return await featured_service.update_copy(db, payload)


@admin_router.post("/items", response_model=FeaturedItemRead, status_code=status.HTTP_201_CREATED)
async def create_featured_item(db: DbSession, payload: FeaturedItemWrite) -> FeaturedItemRead:
    return await featured_service.create_item(db, payload)


@admin_router.put("/items/order", response_model=FeaturedAdmin)
async def reorder_featured_items(db: DbSession, payload: FeaturedReorder) -> FeaturedAdmin:
    return await featured_service.reorder(db, payload)


@admin_router.patch("/items/{item_id}", response_model=FeaturedItemRead)
async def update_featured_item(
    db: DbSession, item_id: uuid.UUID, payload: FeaturedItemWrite
) -> FeaturedItemRead:
    item = await featured_service.get_item(db, item_id)
    return await featured_service.update_item(db, item, payload)


@admin_router.delete("/items/{item_id}", response_model=Message)
async def delete_featured_item(db: DbSession, item_id: uuid.UUID) -> Message:
    item = await featured_service.get_item(db, item_id)
    await featured_service.delete_item(db, item)
    return Message(message="Featured product removed")
