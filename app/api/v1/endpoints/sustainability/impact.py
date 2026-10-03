import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.common import Message
from app.schemas.sustainability.impact import (
    ImpactAdmin,
    ImpactCopyUpdate,
    ImpactItemRead,
    ImpactItemWrite,
    ImpactPublic,
    ImpactReorder,
)
from app.services.sustainability import impact_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=ImpactPublic)
async def read_sustainability_impact(db: DbSession) -> ImpactPublic:
    return await impact_service.public_view(db)


@admin_router.get("", response_model=ImpactAdmin)
async def list_sustainability_impact(db: DbSession) -> ImpactAdmin:
    return await impact_service.admin_view(db)


@admin_router.patch("", response_model=ImpactAdmin)
async def update_sustainability_impact_copy(
    db: DbSession, payload: ImpactCopyUpdate
) -> ImpactAdmin:
    return await impact_service.update_copy(db, payload)


@admin_router.post("/items", response_model=ImpactItemRead, status_code=status.HTTP_201_CREATED)
async def create_sustainability_impact_item(
    db: DbSession, payload: ImpactItemWrite
) -> ImpactItemRead:
    return await impact_service.create_item(db, payload)


@admin_router.put("/items/order", response_model=ImpactAdmin)
async def reorder_sustainability_impact(db: DbSession, payload: ImpactReorder) -> ImpactAdmin:
    return await impact_service.reorder(db, payload)


@admin_router.patch("/items/{item_id}", response_model=ImpactItemRead)
async def update_sustainability_impact_item(
    db: DbSession, item_id: uuid.UUID, payload: ImpactItemWrite
) -> ImpactItemRead:
    item = await impact_service.get_item(db, item_id)
    return await impact_service.update_item(db, item, payload)


@admin_router.delete("/items/{item_id}", response_model=Message)
async def delete_sustainability_impact_item(db: DbSession, item_id: uuid.UUID) -> Message:
    item = await impact_service.get_item(db, item_id)
    await impact_service.delete_item(db, item)
    return Message(message="Stat removed")
