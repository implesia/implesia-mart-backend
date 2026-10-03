import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from pydantic import ValidationError

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.rate_limit import limiter
from app.schemas.common import Message
from app.schemas.home.category import (
    CategoryAdmin,
    CategoryHeadingUpdate,
    CategoryPublic,
    CategoryReorder,
    CategoryTileRead,
    CategoryTileUpdate,
    CategoryTileWrite,
)
from app.services.home import category_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 20_000


def _tile_payload(
    raw: str, model: type[CategoryTileWrite] | type[CategoryTileUpdate]
) -> CategoryTileWrite | CategoryTileUpdate:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Category details are too large")
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid") from exc


@public_router.get("", response_model=CategoryPublic)
async def read_home_categories(db: DbSession) -> CategoryPublic:
    return await category_service.public_view(db)


@admin_router.get("", response_model=CategoryAdmin)
async def list_categories(db: DbSession) -> CategoryAdmin:
    return await category_service.admin_view(db)


@admin_router.patch("", response_model=CategoryAdmin)
async def update_category_heading(db: DbSession, payload: CategoryHeadingUpdate) -> CategoryAdmin:
    return await category_service.update_heading(db, payload)


@admin_router.post("/tiles", response_model=CategoryTileRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def create_category_tile(
    request: Request,
    db: DbSession,
    payload: Annotated[str, Form()],
    image: Annotated[UploadFile | None, File()] = None,
) -> CategoryTileRead:
    del request
    data = _tile_payload(payload, CategoryTileWrite)
    assert isinstance(data, CategoryTileWrite)
    return await category_service.create_tile(db, data, image)


@admin_router.put("/tiles/order", response_model=CategoryAdmin)
async def reorder_category_tiles(db: DbSession, payload: CategoryReorder) -> CategoryAdmin:
    return await category_service.reorder(db, payload)


@admin_router.patch("/tiles/{tile_id}", response_model=CategoryTileRead)
@limiter.limit(settings.rate_limit_product_writes)
async def update_category_tile(
    request: Request,
    db: DbSession,
    tile_id: uuid.UUID,
    payload: Annotated[str, Form()] = "{}",
    image: Annotated[UploadFile | None, File()] = None,
) -> CategoryTileRead:
    del request
    data = _tile_payload(payload, CategoryTileUpdate)
    assert isinstance(data, CategoryTileUpdate)
    tile = await category_service.get_tile(db, tile_id)
    return await category_service.update_tile(db, tile, data, image)


@admin_router.delete("/tiles/{tile_id}", response_model=Message)
async def delete_category_tile(db: DbSession, tile_id: uuid.UUID) -> Message:
    tile = await category_service.get_tile(db, tile_id)
    await category_service.delete_tile(db, tile)
    return Message(message="Category deleted")
