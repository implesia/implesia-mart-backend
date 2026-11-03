from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.api.deps import DbSession, no_store, require_editor
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.payment import PaymentSettingsAdmin, PaymentSettingsPublic
from app.services import payment_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=PaymentSettingsPublic, dependencies=[Depends(no_store)])
async def read_payment(db: DbSession) -> PaymentSettingsPublic:
    """The Bangla QR image (null when none is set). Live from the database, never cached."""
    return await payment_service.public_view(db)


@admin_router.get("", response_model=PaymentSettingsAdmin)
async def read_payment_admin(db: DbSession) -> PaymentSettingsAdmin:
    return await payment_service.admin_view(db)


@admin_router.post("/qr", response_model=PaymentSettingsAdmin)
@limiter.limit(settings.rate_limit_product_writes)
async def upload_payment_qr(
    request: Request, db: DbSession, image: Annotated[UploadFile, File()]
) -> PaymentSettingsAdmin:
    """Upload or replace the Bangla QR image. The old file is deleted."""
    del request
    return await payment_service.upload_qr(db, image)


@admin_router.delete("/qr", response_model=PaymentSettingsAdmin)
async def delete_payment_qr(db: DbSession) -> PaymentSettingsAdmin:
    return await payment_service.delete_qr(db)
