import hashlib
import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status
from limits import parse

from app.api.deps import DbSession, RequireEditor, no_store, require_editor
from app.core.config import settings
from app.core.exceptions import TooManyRequestsError
from app.rate_limit import _rate_limit_key, limiter
from app.schemas.inquiry import (
    InquiryAdmin,
    InquiryCounts,
    InquiryCreate,
    InquiryList,
    InquiryQuery,
    InquiryReceipt,
    InquiryUpdate,
)
from app.services import inquiry_service

public_router = APIRouter(dependencies=[Depends(no_store)])
admin_router = APIRouter(dependencies=[Depends(no_store), Depends(require_editor)])

_INQUIRY_LIMIT = parse(settings.rate_limit_inquiries)


def _bucket(request: Request) -> tuple[str, str]:
    """Per-IP bucket keyed by a salted hash, so Redis never holds a raw address."""
    secret = settings.secret_key.encode()
    digest = hmac.new(secret, _rate_limit_key(request).encode(), hashlib.sha256).hexdigest()
    return ("inquiries", digest[:32])


@public_router.post("", response_model=InquiryReceipt, status_code=status.HTTP_201_CREATED)
async def submit_inquiry(
    request: Request,
    db: DbSession,
    payload: InquiryCreate,
    idempotency_key: Annotated[str | None, Header(max_length=80)] = None,
) -> InquiryReceipt:
    replay = await inquiry_service.replayed(db, idempotency_key)
    if replay is not None:
        return replay  # a double click does not spend the budget or add a row
    bucket = _bucket(request)
    if limiter.enabled and not limiter.limiter.test(_INQUIRY_LIMIT, *bucket):
        raise TooManyRequestsError("Too many messages. Please try again a little later.")
    if limiter.enabled:
        limiter.limiter.hit(_INQUIRY_LIMIT, *bucket)
    if inquiry_service.is_bot(payload):
        return inquiry_service.decoy_receipt()
    return await inquiry_service.create_inquiry(db, payload, idempotency_key)


@admin_router.get("", response_model=InquiryList)
async def list_inquiries(db: DbSession, query: Annotated[InquiryQuery, Depends()]) -> InquiryList:
    return await inquiry_service.list_inquiries(db, query)


@admin_router.get("/counts", response_model=InquiryCounts)
async def inquiry_counts(db: DbSession) -> InquiryCounts:
    return await inquiry_service.counts(db)


@admin_router.get("/{inquiry_id}", response_model=InquiryAdmin)
async def read_inquiry(db: DbSession, inquiry_id: uuid.UUID) -> InquiryAdmin:
    return await inquiry_service.get_inquiry(db, inquiry_id)


@admin_router.patch("/{inquiry_id}", response_model=InquiryAdmin)
async def update_inquiry(
    db: DbSession, actor: RequireEditor, inquiry_id: uuid.UUID, payload: InquiryUpdate
) -> InquiryAdmin:
    return await inquiry_service.update_inquiry(db, inquiry_id, payload, actor)


@admin_router.delete("/{inquiry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inquiry(db: DbSession, inquiry_id: uuid.UUID) -> Response:
    await inquiry_service.delete_inquiry(db, inquiry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
