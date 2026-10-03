import uuid

from fastapi import APIRouter, Depends, Form, Request, UploadFile, status
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUpload

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.rate_limit import limiter
from app.schemas.about_story import StoriesPublic, StoryRead, StoryReorder, StoryWrite
from app.schemas.common import Message
from app.services import about_story_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 40_000


def _payload(raw: str) -> StoryWrite:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Story details are too large")
    try:
        return StoryWrite.model_validate_json(raw)
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


@public_router.get("", response_model=StoriesPublic)
async def read_about_stories(db: DbSession) -> StoriesPublic:
    return await about_story_service.public_stories(db)


@admin_router.get("", response_model=list[StoryRead])
async def list_about_stories(db: DbSession) -> list[StoryRead]:
    return await about_story_service.list_stories(db)


@admin_router.post("", response_model=StoryRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_product_writes)
async def create_about_story(
    request: Request, db: DbSession, payload: str = Form()
) -> StoryRead:
    form = await request.form()
    return await about_story_service.create_story(
        db, _payload(payload), _uploads(list(form.multi_items()))
    )


@admin_router.put("/order", response_model=list[StoryRead])
async def reorder_about_stories(db: DbSession, payload: StoryReorder) -> list[StoryRead]:
    return await about_story_service.reorder(db, payload)


@admin_router.patch("/{story_id}", response_model=StoryRead)
@limiter.limit(settings.rate_limit_product_writes)
async def update_about_story(
    request: Request, db: DbSession, story_id: uuid.UUID, payload: str = Form()
) -> StoryRead:
    form = await request.form()
    block = await about_story_service.get_story(db, story_id)
    return await about_story_service.update_story(
        db, block, _payload(payload), _uploads(list(form.multi_items()))
    )


@admin_router.delete("/{story_id}", response_model=Message)
async def delete_about_story(db: DbSession, story_id: uuid.UUID) -> Message:
    block = await about_story_service.get_story(db, story_id)
    await about_story_service.delete_story(db, block)
    return Message(message="Story removed")
