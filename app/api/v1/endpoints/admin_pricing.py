from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession, RequireEditor, no_store
from app.schemas.pricing import PricingSettingsRead, PricingSettingsUpdate
from app.services import pricing_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("", response_model=PricingSettingsRead)
async def read_pricing_settings(db: DbSession, user: CurrentUser) -> PricingSettingsRead:
    del user
    return await pricing_service.get_settings(db)


@router.put("", response_model=PricingSettingsRead)
async def update_pricing_settings(
    db: DbSession, user: RequireEditor, payload: PricingSettingsUpdate
) -> PricingSettingsRead:
    del user
    return await pricing_service.set_settings(db, payload)
