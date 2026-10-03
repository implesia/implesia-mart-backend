from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.rate_limit import limiter
from app.schemas.about.hero import AboutHeroAdmin, AboutHeroPublic, AboutHeroWrite
from app.services.about import hero_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 20_000


def _payload(raw: str) -> AboutHeroWrite:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Hero details are too large")
    try:
        return AboutHeroWrite.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid") from exc


@public_router.get("", response_model=AboutHeroPublic)
async def read_about_hero(db: DbSession) -> AboutHeroPublic:
    return await hero_service.public_view(db)


@admin_router.get("", response_model=AboutHeroAdmin)
async def read_admin_about_hero(db: DbSession) -> AboutHeroAdmin:
    return await hero_service.admin_view(db)


@admin_router.put("", response_model=AboutHeroAdmin)
@limiter.limit(settings.rate_limit_product_writes)
async def update_about_hero(
    request: Request,
    db: DbSession,
    payload: Annotated[str, Form()],
    image_0: Annotated[UploadFile | None, File()] = None,
    image_1: Annotated[UploadFile | None, File()] = None,
) -> AboutHeroAdmin:
    del request
    data = _payload(payload)
    return await hero_service.update_hero(db, data, image_0, image_1)
