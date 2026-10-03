import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.about_steps import (
    StepItemRead,
    StepItemWrite,
    StepReorder,
    StepsAdmin,
    StepsCopyUpdate,
    StepsPublic,
)
from app.schemas.common import Message
from app.services import about_steps_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=StepsPublic)
async def read_about_steps(db: DbSession) -> StepsPublic:
    return await about_steps_service.public_view(db)


@admin_router.get("", response_model=StepsAdmin)
async def list_about_steps(db: DbSession) -> StepsAdmin:
    return await about_steps_service.admin_view(db)


@admin_router.patch("", response_model=StepsAdmin)
async def update_about_steps_copy(db: DbSession, payload: StepsCopyUpdate) -> StepsAdmin:
    return await about_steps_service.update_copy(db, payload)


@admin_router.post("/items", response_model=StepItemRead, status_code=status.HTTP_201_CREATED)
async def create_about_step(db: DbSession, payload: StepItemWrite) -> StepItemRead:
    return await about_steps_service.create_item(db, payload)


@admin_router.put("/items/order", response_model=StepsAdmin)
async def reorder_about_steps(db: DbSession, payload: StepReorder) -> StepsAdmin:
    return await about_steps_service.reorder(db, payload)


@admin_router.patch("/items/{item_id}", response_model=StepItemRead)
async def update_about_step(
    db: DbSession, item_id: uuid.UUID, payload: StepItemWrite
) -> StepItemRead:
    item = await about_steps_service.get_item(db, item_id)
    return await about_steps_service.update_item(db, item, payload)


@admin_router.delete("/items/{item_id}", response_model=Message)
async def delete_about_step(db: DbSession, item_id: uuid.UUID) -> Message:
    item = await about_steps_service.get_item(db, item_id)
    await about_steps_service.delete_item(db, item)
    return Message(message="Step removed")
