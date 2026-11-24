from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_module_for_method
from app.schemas.pricing import PricingSettingsRead, PricingSettingsUpdate
from app.services import pricing_service

router = APIRouter(
    dependencies=[Depends(no_store), Depends(require_module_for_method("coupons_pricing"))]
)


@router.get("", response_model=PricingSettingsRead)
async def read_pricing_settings(db: DbSession) -> PricingSettingsRead:
    return await pricing_service.get_settings(db)


@router.put("", response_model=PricingSettingsRead)
async def update_pricing_settings(
    db: DbSession, payload: PricingSettingsUpdate
) -> PricingSettingsRead:
    return await pricing_service.set_settings(db, payload)
