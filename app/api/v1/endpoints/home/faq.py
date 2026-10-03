import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.common import Message
from app.schemas.home.faq import (
    FaqAdmin,
    FaqCopyUpdate,
    FaqItemRead,
    FaqItemUpdate,
    FaqItemWrite,
    FaqPublic,
    FaqReorder,
)
from app.services.home import faq_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=FaqPublic)
async def read_home_faq(db: DbSession) -> FaqPublic:
    return await faq_service.public_view(db)


@admin_router.get("", response_model=FaqAdmin)
async def list_faq_items(db: DbSession) -> FaqAdmin:
    return await faq_service.admin_view(db)


@admin_router.patch("", response_model=FaqAdmin)
async def update_faq_copy(db: DbSession, payload: FaqCopyUpdate) -> FaqAdmin:
    return await faq_service.update_copy(db, payload)


@admin_router.post("/items", response_model=FaqItemRead, status_code=status.HTTP_201_CREATED)
async def create_faq_item(db: DbSession, payload: FaqItemWrite) -> FaqItemRead:
    return await faq_service.create_item(db, payload)


@admin_router.put("/items/order", response_model=FaqAdmin)
async def reorder_faq_items(db: DbSession, payload: FaqReorder) -> FaqAdmin:
    return await faq_service.reorder(db, payload)


@admin_router.patch("/items/{item_id}", response_model=FaqItemRead)
async def update_faq_item(db: DbSession, item_id: uuid.UUID, payload: FaqItemUpdate) -> FaqItemRead:
    item = await faq_service.get_item(db, item_id)
    return await faq_service.update_item(db, item, payload)


@admin_router.delete("/items/{item_id}", response_model=Message)
async def delete_faq_item(db: DbSession, item_id: uuid.UUID) -> Message:
    item = await faq_service.get_item(db, item_id)
    await faq_service.delete_item(db, item)
    return Message(message="Question removed")
