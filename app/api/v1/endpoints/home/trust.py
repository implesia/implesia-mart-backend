import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.common import Message
from app.schemas.home.trust import (
    TrustItemRead,
    TrustItemUpdate,
    TrustItemWrite,
    TrustPublic,
    TrustReorder,
)
from app.services.home import trust_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=TrustPublic)
async def read_home_trust(db: DbSession) -> TrustPublic:
    return await trust_service.public_items(db)


@admin_router.get("", response_model=list[TrustItemRead])
async def list_trust_items(db: DbSession) -> list[TrustItemRead]:
    return await trust_service.list_items(db)


@admin_router.post("", response_model=TrustItemRead, status_code=status.HTTP_201_CREATED)
async def create_trust_item(db: DbSession, payload: TrustItemWrite) -> TrustItemRead:
    return await trust_service.create_item(db, payload)


@admin_router.put("/order", response_model=list[TrustItemRead])
async def reorder_trust_items(db: DbSession, payload: TrustReorder) -> list[TrustItemRead]:
    return await trust_service.reorder(db, payload)


@admin_router.patch("/{item_id}", response_model=TrustItemRead)
async def update_trust_item(
    db: DbSession, item_id: uuid.UUID, payload: TrustItemUpdate
) -> TrustItemRead:
    item = await trust_service.get_item(db, item_id)
    return await trust_service.update_item(db, item, payload)


@admin_router.delete("/{item_id}", response_model=Message)
async def delete_trust_item(db: DbSession, item_id: uuid.UUID) -> Message:
    item = await trust_service.get_item(db, item_id)
    await trust_service.delete_item(db, item)
    return Message(message="Trust benefit deleted")
