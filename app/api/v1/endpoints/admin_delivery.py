from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession, RequireEditor, no_store
from app.schemas.delivery import DeliveryRatesRead, DeliveryRatesUpdate
from app.services import delivery_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("", response_model=DeliveryRatesRead)
async def read_delivery_rates(db: DbSession, user: CurrentUser) -> DeliveryRatesRead:
    del user
    return await delivery_service.get_rates(db)


@router.patch("", response_model=DeliveryRatesRead)
async def update_delivery_rates(
    db: DbSession,
    user: RequireEditor,
    payload: DeliveryRatesUpdate,
) -> DeliveryRatesRead:
    del user
    return await delivery_service.set_rates(db, payload)
