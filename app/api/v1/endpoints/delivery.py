from fastapi import APIRouter, Response

from app.api.deps import DbSession
from app.schemas.delivery import DeliveryRatesRead
from app.services import delivery_service

router = APIRouter()


@router.get("", response_model=DeliveryRatesRead)
async def read_delivery_rates(response: Response, db: DbSession) -> DeliveryRatesRead:
    response.headers["Cache-Control"] = "public, max-age=60"
    return await delivery_service.get_rates(db)
