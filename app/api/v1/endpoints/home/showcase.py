import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.common import Message
from app.schemas.home.showcase import (
    ShowcaseAdmin,
    ShowcaseItemRead,
    ShowcaseItemWrite,
    ShowcasePublic,
    ShowcaseReorder,
    ShowcaseRowUpdate,
)
from app.services.home import showcase_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=ShowcasePublic)
async def read_home_showcase(db: DbSession) -> ShowcasePublic:
    return await showcase_service.public_view(db)


@admin_router.get("", response_model=ShowcaseAdmin)
async def list_showcase(db: DbSession) -> ShowcaseAdmin:
    return await showcase_service.admin_view(db)


@admin_router.patch("/rows/{key}", response_model=ShowcaseAdmin)
async def update_showcase_row(
    db: DbSession, key: str, payload: ShowcaseRowUpdate
) -> ShowcaseAdmin:
    row = await showcase_service.get_row(db, key)
    return await showcase_service.update_row(db, row, payload)


@admin_router.post(
    "/rows/{key}/items",
    response_model=ShowcaseItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_showcase_item(
    db: DbSession, key: str, payload: ShowcaseItemWrite
) -> ShowcaseItemRead:
    row = await showcase_service.get_row(db, key)
    return await showcase_service.create_item(db, row, payload)


@admin_router.put("/rows/{key}/items/order", response_model=ShowcaseAdmin)
async def reorder_showcase_items(
    db: DbSession, key: str, payload: ShowcaseReorder
) -> ShowcaseAdmin:
    row = await showcase_service.get_row(db, key)
    return await showcase_service.reorder(db, row, payload)


@admin_router.patch("/rows/{key}/items/{item_id}", response_model=ShowcaseItemRead)
async def update_showcase_item(
    db: DbSession, key: str, item_id: uuid.UUID, payload: ShowcaseItemWrite
) -> ShowcaseItemRead:
    row = await showcase_service.get_row(db, key)
    item = await showcase_service.get_item(db, row, item_id)
    return await showcase_service.update_item(db, row, item, payload)


@admin_router.delete("/rows/{key}/items/{item_id}", response_model=Message)
async def delete_showcase_item(db: DbSession, key: str, item_id: uuid.UUID) -> Message:
    row = await showcase_service.get_row(db, key)
    item = await showcase_service.get_item(db, row, item_id)
    await showcase_service.delete_item(db, item)
    return Message(message="Showcase product removed")
