import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.about.stats import (
    StatItemRead,
    StatItemUpdate,
    StatItemWrite,
    StatReorder,
    StatsPublic,
)
from app.schemas.common import Message
from app.services.about import stats_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=StatsPublic)
async def read_about_stats(db: DbSession) -> StatsPublic:
    return await stats_service.public_items(db)


@admin_router.get("", response_model=list[StatItemRead])
async def list_about_stats(db: DbSession) -> list[StatItemRead]:
    return await stats_service.list_items(db)


@admin_router.post("", response_model=StatItemRead, status_code=status.HTTP_201_CREATED)
async def create_about_stat(db: DbSession, payload: StatItemWrite) -> StatItemRead:
    return await stats_service.create_item(db, payload)


@admin_router.put("/order", response_model=list[StatItemRead])
async def reorder_about_stats(db: DbSession, payload: StatReorder) -> list[StatItemRead]:
    return await stats_service.reorder(db, payload)


@admin_router.patch("/{item_id}", response_model=StatItemRead)
async def update_about_stat(
    db: DbSession, item_id: uuid.UUID, payload: StatItemUpdate
) -> StatItemRead:
    item = await stats_service.get_item(db, item_id)
    return await stats_service.update_item(db, item, payload)


@admin_router.delete("/{item_id}", response_model=Message)
async def delete_about_stat(db: DbSession, item_id: uuid.UUID) -> Message:
    item = await stats_service.get_item(db, item_id)
    await stats_service.delete_item(db, item)
    return Message(message="Stat removed")
