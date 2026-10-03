import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.common import Message
from app.schemas.faqs.items import ItemRead, ItemReorder, ItemsAdmin, ItemsPublic, ItemWrite
from app.services.faqs import items_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=ItemsPublic)
async def read_faq_items(db: DbSession) -> ItemsPublic:
    return await items_service.public_view(db)


@admin_router.get("", response_model=ItemsAdmin)
async def list_faq_items(db: DbSession) -> ItemsAdmin:
    return await items_service.admin_view(db)


@admin_router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
async def create_faq_item(db: DbSession, payload: ItemWrite) -> ItemRead:
    return await items_service.create_item(db, payload)


@admin_router.put("/order", response_model=ItemsAdmin)
async def reorder_faq_items(db: DbSession, payload: ItemReorder) -> ItemsAdmin:
    return await items_service.reorder(db, payload)


@admin_router.patch("/{item_id}", response_model=ItemRead)
async def update_faq_item(db: DbSession, item_id: uuid.UUID, payload: ItemWrite) -> ItemRead:
    item = await items_service.get_item(db, item_id)
    return await items_service.update_item(db, item, payload)


@admin_router.delete("/{item_id}", response_model=Message)
async def delete_faq_item(db: DbSession, item_id: uuid.UUID) -> Message:
    item = await items_service.get_item(db, item_id)
    await items_service.delete_item(db, item)
    return Message(message="Question removed")
