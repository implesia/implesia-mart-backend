import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.about_values import (
    ValueItemRead,
    ValueItemWrite,
    ValueReorder,
    ValuesAdmin,
    ValuesCopyUpdate,
    ValuesPublic,
)
from app.schemas.common import Message
from app.services import about_values_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=ValuesPublic)
async def read_about_values(db: DbSession) -> ValuesPublic:
    return await about_values_service.public_view(db)


@admin_router.get("", response_model=ValuesAdmin)
async def list_about_values(db: DbSession) -> ValuesAdmin:
    return await about_values_service.admin_view(db)


@admin_router.patch("", response_model=ValuesAdmin)
async def update_about_values_copy(db: DbSession, payload: ValuesCopyUpdate) -> ValuesAdmin:
    return await about_values_service.update_copy(db, payload)


@admin_router.post("/items", response_model=ValueItemRead, status_code=status.HTTP_201_CREATED)
async def create_about_value(db: DbSession, payload: ValueItemWrite) -> ValueItemRead:
    return await about_values_service.create_item(db, payload)


@admin_router.put("/items/order", response_model=ValuesAdmin)
async def reorder_about_values(db: DbSession, payload: ValueReorder) -> ValuesAdmin:
    return await about_values_service.reorder(db, payload)


@admin_router.patch("/items/{item_id}", response_model=ValueItemRead)
async def update_about_value(
    db: DbSession, item_id: uuid.UUID, payload: ValueItemWrite
) -> ValueItemRead:
    item = await about_values_service.get_item(db, item_id)
    return await about_values_service.update_item(db, item, payload)


@admin_router.delete("/items/{item_id}", response_model=Message)
async def delete_about_value(db: DbSession, item_id: uuid.UUID) -> Message:
    item = await about_values_service.get_item(db, item_id)
    await about_values_service.delete_item(db, item)
    return Message(message="Value removed")
