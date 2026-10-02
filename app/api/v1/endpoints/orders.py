from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.api.deps import DbSession, no_store
from app.api.v1.endpoints.cart import ShopperDep
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.order import OrderCreate, OrderQuoteRequest, OrderRead, QuoteRead
from app.services import order_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.post("/quote", response_model=QuoteRead)
@limiter.limit(settings.rate_limit_cart_writes)
async def quote_order(
    request: Request,
    db: DbSession,
    actor: ShopperDep,
    payload: OrderQuoteRequest,
) -> QuoteRead:
    del request
    return await order_service.quote(db, actor, payload)


@router.post("", response_model=OrderRead, status_code=201)
@limiter.limit(settings.rate_limit_orders)
async def place_order(
    request: Request,
    db: DbSession,
    actor: ShopperDep,
    payload: OrderCreate,
    idempotency_key: Annotated[str, Header()],
) -> OrderRead:
    del request
    return await order_service.create_order(db, actor, payload, idempotency_key)
