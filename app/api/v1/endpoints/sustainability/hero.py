from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.rate_limit import limiter
from app.schemas.sustainability.hero import (
    SustainabilityHeroAdmin,
    SustainabilityHeroPublic,
    SustainabilityHeroWrite,
)
from app.services.sustainability import hero_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 20_000


def _payload(raw: str) -> SustainabilityHeroWrite:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Hero details are too large")
    try:
        return SustainabilityHeroWrite.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid") from exc


@public_router.get("", response_model=SustainabilityHeroPublic)
async def read_sustainability_hero(db: DbSession) -> SustainabilityHeroPublic:
    return await hero_service.public_view(db)


@admin_router.get("", response_model=SustainabilityHeroAdmin)
async def read_admin_sustainability_hero(db: DbSession) -> SustainabilityHeroAdmin:
    return await hero_service.admin_view(db)


@admin_router.put("", response_model=SustainabilityHeroAdmin)
@limiter.limit(settings.rate_limit_product_writes)
async def update_sustainability_hero(
    request: Request,
    db: DbSession,
    payload: Annotated[str, Form()],
    image_0: Annotated[UploadFile | None, File()] = None,
    image_1: Annotated[UploadFile | None, File()] = None,
) -> SustainabilityHeroAdmin:
    del request
    data = _payload(payload)
    return await hero_service.update_hero(db, data, image_0, image_1)
