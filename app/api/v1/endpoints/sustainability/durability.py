from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.rate_limit import limiter
from app.schemas.sustainability.durability import DurabilityAdmin, DurabilityPublic, DurabilityWrite
from app.services.sustainability import durability_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])

_PAYLOAD_LIMIT = 40_000


def _payload(raw: str) -> DurabilityWrite:
    if len(raw.encode("utf-8")) > _PAYLOAD_LIMIT:
        raise UnprocessableError("Durability details are too large")
    try:
        return DurabilityWrite.model_validate_json(raw)
    except ValidationError as exc:
        raise UnprocessableError("Request payload is invalid") from exc


@public_router.get("", response_model=DurabilityPublic)
async def read_sustainability_durability(db: DbSession) -> DurabilityPublic:
    return await durability_service.public_view(db)


@admin_router.get("", response_model=DurabilityAdmin)
async def read_admin_sustainability_durability(db: DbSession) -> DurabilityAdmin:
    return await durability_service.admin_view(db)


@admin_router.put("", response_model=DurabilityAdmin)
@limiter.limit(settings.rate_limit_product_writes)
async def update_sustainability_durability(
    request: Request,
    db: DbSession,
    payload: Annotated[str, Form()],
    image_0: Annotated[UploadFile | None, File()] = None,
) -> DurabilityAdmin:
    del request
    return await durability_service.update_durability(db, _payload(payload), image_0)
