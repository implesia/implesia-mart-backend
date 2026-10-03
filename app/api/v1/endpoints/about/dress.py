import uuid

from fastapi import APIRouter, Depends, Form, Request, UploadFile, status
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUpload

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.rate_limit import limiter
from app.schemas.about.dress import DressesPublic, DressRead, DressReorder, DressWrite
from app.schemas.common import Message
from app.services.about import dress_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 40_000


def _payload(raw: str) -> DressWrite:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Custom dress details are too large")
    try:
        return DressWrite.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid") from exc


def _uploads(form_items: list[tuple[str, object]]) -> dict[int, UploadFile]:
    uploads: dict[int, UploadFile] = {}
    for key, value in form_items:
        if not key.startswith("image_"):
            continue
        suffix = key.removeprefix("image_")
        if suffix.isdigit() and isinstance(value, StarletteUpload):
            uploads[int(suffix)] = value
    return uploads


@public_router.get("", response_model=DressesPublic)
async def read_about_dresses(db: DbSession) -> DressesPublic:
    return await dress_service.public_dresses(db)


@admin_router.get("", response_model=list[DressRead])
async def list_about_dresses(db: DbSession) -> list[DressRead]:
    return await dress_service.list_dresses(db)


@admin_router.post("", response_model=DressRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def create_about_dress(request: Request, db: DbSession, payload: str = Form()) -> DressRead:
    form = await request.form()
    return await dress_service.create_dress(
        db, _payload(payload), _uploads(list(form.multi_items()))
    )


@admin_router.put("/order", response_model=list[DressRead])
async def reorder_about_dresses(db: DbSession, payload: DressReorder) -> list[DressRead]:
    return await dress_service.reorder(db, payload)


@admin_router.patch("/{dress_id}", response_model=DressRead)
@limiter.limit(settings.rate_limit_product_writes)
async def update_about_dress(
    request: Request, db: DbSession, dress_id: uuid.UUID, payload: str = Form()
) -> DressRead:
    form = await request.form()
    block = await dress_service.get_dress(db, dress_id)
    return await dress_service.update_dress(
        db, block, _payload(payload), _uploads(list(form.multi_items()))
    )


@admin_router.delete("/{dress_id}", response_model=Message)
async def delete_about_dress(db: DbSession, dress_id: uuid.UUID) -> Message:
    block = await dress_service.get_dress(db, dress_id)
    await dress_service.delete_dress(db, block)
    return Message(message="Custom dress removed")
