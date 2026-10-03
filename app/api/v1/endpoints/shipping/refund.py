from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.shipping.refund import RefundAdmin, RefundPublic, RefundWrite
from app.services.shipping import refund_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=RefundPublic)
async def read_shipping_refund(db: DbSession) -> RefundPublic:
    return await refund_service.public_view(db)


@admin_router.get("", response_model=RefundAdmin)
async def read_admin_shipping_refund(db: DbSession) -> RefundAdmin:
    return await refund_service.admin_view(db)


@admin_router.patch("", response_model=RefundAdmin)
async def update_shipping_refund(db: DbSession, payload: RefundWrite) -> RefundAdmin:
    return await refund_service.update_refund(db, payload)
