import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.common import Message
from app.schemas.sustainability.commitment import (
    CommitmentAdmin,
    CommitmentCopyUpdate,
    CommitmentItemRead,
    CommitmentItemWrite,
    CommitmentPublic,
    CommitmentReorder,
)
from app.services.sustainability import commitment_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=CommitmentPublic)
async def read_sustainability_commitment(db: DbSession) -> CommitmentPublic:
    return await commitment_service.public_view(db)


@admin_router.get("", response_model=CommitmentAdmin)
async def list_sustainability_commitment(db: DbSession) -> CommitmentAdmin:
    return await commitment_service.admin_view(db)


@admin_router.patch("", response_model=CommitmentAdmin)
async def update_sustainability_commitment_copy(
    db: DbSession, payload: CommitmentCopyUpdate
) -> CommitmentAdmin:
    return await commitment_service.update_copy(db, payload)


@admin_router.post("/items", response_model=CommitmentItemRead, status_code=status.HTTP_201_CREATED)
async def create_sustainability_commitment_item(
    db: DbSession, payload: CommitmentItemWrite
) -> CommitmentItemRead:
    return await commitment_service.create_item(db, payload)


@admin_router.put("/items/order", response_model=CommitmentAdmin)
async def reorder_sustainability_commitment(
    db: DbSession, payload: CommitmentReorder
) -> CommitmentAdmin:
    return await commitment_service.reorder(db, payload)


@admin_router.patch("/items/{item_id}", response_model=CommitmentItemRead)
async def update_sustainability_commitment_item(
    db: DbSession, item_id: uuid.UUID, payload: CommitmentItemWrite
) -> CommitmentItemRead:
    item = await commitment_service.get_item(db, item_id)
    return await commitment_service.update_item(db, item, payload)


@admin_router.delete("/items/{item_id}", response_model=Message)
async def delete_sustainability_commitment_item(db: DbSession, item_id: uuid.UUID) -> Message:
    item = await commitment_service.get_item(db, item_id)
    await commitment_service.delete_item(db, item)
    return Message(message="Card removed")
