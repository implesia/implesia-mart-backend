from fastapi import APIRouter, Response

from app.api.deps import DbSession
from app.schemas.courier import DeliveryLocationsResponse
from app.schemas.delivery import DeliveryRatesRead
from app.services import delivery_service
from app.services.courier import steadfast_service

router = APIRouter()


@router.get("", response_model=DeliveryRatesRead)
async def read_delivery_rates(response: Response, db: DbSession) -> DeliveryRatesRead:
    response.headers["Cache-Control"] = "public, max-age=60"
    return await delivery_service.get_rates(db)


@router.get("/locations", response_model=DeliveryLocationsResponse)
async def read_delivery_locations(
    response: Response, db: DbSession
) -> DeliveryLocationsResponse:
    response.headers["Cache-Control"] = "public, max-age=300"
    return await steadfast_service.get_public_delivery_locations(db)
