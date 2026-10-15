from typing import cast

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUpload

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError, payload_errors
from app.rate_limit import limiter
from app.schemas.sustainability.origin import OriginAdmin, OriginPublic, OriginWrite
from app.services.sustainability import origin_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 40_000


def _payload(raw: str) -> OriginWrite:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Point of view details are too large")
    try:
        return OriginWrite.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid", payload_errors(exc)) from exc


def _upload(form_items: list[tuple[str, object]]) -> UploadFile | None:
    """The single photo arrives as ``image`` (``image_0`` from older admin builds)."""
    found: dict[str, UploadFile] = {}
    for key, value in form_items:
        if key in ("image", "image_0") and isinstance(value, StarletteUpload):
            found[key] = cast(UploadFile, value)
    return found.get("image") or found.get("image_0")


@public_router.get("", response_model=OriginPublic)
async def read_sustainability_origin(db: DbSession) -> OriginPublic:
    return await origin_service.public_view(db)


@admin_router.get("", response_model=OriginAdmin)
async def read_admin_sustainability_origin(db: DbSession) -> OriginAdmin:
    return await origin_service.admin_view(db)


@admin_router.put("", response_model=OriginAdmin)
@limiter.limit(settings.rate_limit_product_writes)
async def update_sustainability_origin(
    request: Request, db: DbSession, payload: str = Form()
) -> OriginAdmin:
    form = await request.form()
    return await origin_service.update_origin(
        db, _payload(payload), _upload(list(form.multi_items()))
    )
