import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from pydantic import ValidationError

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.rate_limit import limiter
from app.schemas.common import Message
from app.schemas.home.review import (
    ReviewAdmin,
    ReviewCopyUpdate,
    ReviewItemRead,
    ReviewItemUpdate,
    ReviewItemWrite,
    ReviewPublic,
    ReviewReorder,
)
from app.services.home import review_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 20_000


def _item_payload(
    raw: str, model: type[ReviewItemWrite] | type[ReviewItemUpdate]
) -> ReviewItemWrite | ReviewItemUpdate:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Review details are too large")
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid") from exc


@public_router.get("", response_model=ReviewPublic)
async def read_home_reviews(db: DbSession) -> ReviewPublic:
    return await review_service.public_view(db)


@admin_router.get("", response_model=ReviewAdmin)
async def list_reviews(db: DbSession) -> ReviewAdmin:
    return await review_service.admin_view(db)


@admin_router.patch("", response_model=ReviewAdmin)
async def update_review_copy(db: DbSession, payload: ReviewCopyUpdate) -> ReviewAdmin:
    return await review_service.update_copy(db, payload)


@admin_router.post("/items", response_model=ReviewItemRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def create_review_item(
    request: Request,
    db: DbSession,
    payload: Annotated[str, Form()],
    image: Annotated[UploadFile | None, File()] = None,
) -> ReviewItemRead:
    del request
    data = _item_payload(payload, ReviewItemWrite)
    assert isinstance(data, ReviewItemWrite)
    return await review_service.create_item(db, data, image)


@admin_router.put("/items/order", response_model=ReviewAdmin)
async def reorder_review_items(db: DbSession, payload: ReviewReorder) -> ReviewAdmin:
    return await review_service.reorder(db, payload)


@admin_router.patch("/items/{item_id}", response_model=ReviewItemRead)
@limiter.limit(settings.rate_limit_product_writes)
async def update_review_item(
    request: Request,
    db: DbSession,
    item_id: uuid.UUID,
    payload: Annotated[str, Form()] = "{}",
    image: Annotated[UploadFile | None, File()] = None,
) -> ReviewItemRead:
    del request
    data = _item_payload(payload, ReviewItemUpdate)
    assert isinstance(data, ReviewItemUpdate)
    item = await review_service.get_item(db, item_id)
    return await review_service.update_item(db, item, data, image)


@admin_router.delete("/items/{item_id}", response_model=Message)
async def delete_review_item(db: DbSession, item_id: uuid.UUID) -> Message:
    item = await review_service.get_item(db, item_id)
    await review_service.delete_item(db, item)
    return Message(message="Review removed")
