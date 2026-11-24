from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_module_for_method
from app.schemas.delivery import DeliveryRatesRead, DeliveryRatesUpdate
from app.services import delivery_service

router = APIRouter(
    dependencies=[Depends(no_store), Depends(require_module_for_method("coupons_pricing"))]
)


@router.get("", response_model=DeliveryRatesRead)
async def read_delivery_rates(db: DbSession) -> DeliveryRatesRead:
    return await delivery_service.get_rates(db)


@router.patch("", response_model=DeliveryRatesRead)
async def update_delivery_rates(
    db: DbSession,
    payload: DeliveryRatesUpdate,
) -> DeliveryRatesRead:
    return await delivery_service.set_rates(db, payload)
