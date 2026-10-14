from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from limits import parse

from app.api.deps import DbSession, no_store
from app.api.v1.endpoints.cart import ShopperDep
from app.core.config import settings
from app.core.exceptions import TooManyRequestsError
from app.rate_limit import _rate_limit_key, limiter
from app.schemas.order import (
    OrderCreate,
    OrderLookup,
    OrderQuoteRequest,
    OrderRead,
    PublicOrderRead,
    QuoteRead,
)
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


@router.post("/lookup", response_model=PublicOrderRead)
@limiter.limit(settings.rate_limit_order_lookup)
async def lookup_order(
    request: Request,
    db: DbSession,
    payload: OrderLookup,
) -> PublicOrderRead:
    del request
    return await order_service.lookup_order(db, payload)


_ORDER_LIMIT = parse(settings.rate_limit_orders)


@router.post("", response_model=OrderRead, status_code=201)
async def place_order(
    request: Request,
    db: DbSession,
    actor: ShopperDep,
    payload: OrderCreate,
    idempotency_key: Annotated[str, Header()],
) -> OrderRead:
    # Only placed orders spend the per-IP budget: a replay of the same Idempotency-Key and a
    # submission rejected as invalid (empty cart, stock, delivery area) do not count.
    replay = await order_service.replayed(db, actor, idempotency_key)
    if replay is not None:
        return replay
    bucket = ("orders-placed", _rate_limit_key(request))
    if limiter.enabled and not limiter.limiter.test(_ORDER_LIMIT, *bucket):
        raise TooManyRequestsError("Too many requests.")
    order = await order_service.create_order(db, actor, payload, idempotency_key)
    if limiter.enabled:
        limiter.limiter.hit(_ORDER_LIMIT, *bucket)
    return order
