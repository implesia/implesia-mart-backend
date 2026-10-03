from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.rate_limit import limiter
from app.schemas.sustainability.quality import QualityAdmin, QualityPublic, QualityWrite
from app.services.sustainability import quality_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 40_000


def _payload(raw: str) -> QualityWrite:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Quality details are too large")
    try:
        return QualityWrite.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid") from exc


@public_router.get("", response_model=QualityPublic)
async def read_sustainability_quality(db: DbSession) -> QualityPublic:
    return await quality_service.public_view(db)


@admin_router.get("", response_model=QualityAdmin)
async def read_admin_sustainability_quality(db: DbSession) -> QualityAdmin:
    return await quality_service.admin_view(db)


@admin_router.put("", response_model=QualityAdmin)
@limiter.limit(settings.rate_limit_product_writes)
async def update_sustainability_quality(
    request: Request,
    db: DbSession,
    payload: Annotated[str, Form()],
    image_0: Annotated[UploadFile | None, File()] = None,
) -> QualityAdmin:
    del request
    return await quality_service.update_quality(db, _payload(payload), image_0)
