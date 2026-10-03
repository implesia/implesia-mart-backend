from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.shipping.payment import PaymentAdmin, PaymentPublic, PaymentWrite
from app.services.shipping import payment_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=PaymentPublic)
async def read_shipping_payment(db: DbSession) -> PaymentPublic:
    return await payment_service.public_view(db)


@admin_router.get("", response_model=PaymentAdmin)
async def read_admin_shipping_payment(db: DbSession) -> PaymentAdmin:
    return await payment_service.admin_view(db)


@admin_router.patch("", response_model=PaymentAdmin)
async def update_shipping_payment(db: DbSession, payload: PaymentWrite) -> PaymentAdmin:
    return await payment_service.update_payment(db, payload)
