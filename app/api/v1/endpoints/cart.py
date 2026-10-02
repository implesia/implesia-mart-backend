import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.api.deps import DbSession, OptionalUser, no_store
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.cart import CartItemCreate, CartItemUpdate, CartRead
from app.services import cart_service
from app.services.cart_service import Shopper

router = APIRouter(dependencies=[Depends(no_store)])


async def shopper(
    user: OptionalUser,
    x_cart_token: Annotated[str | None, Header()] = None,
) -> Shopper:
    return Shopper(user=user, guest_token=x_cart_token)


ShopperDep = Annotated[Shopper, Depends(shopper)]


@router.get("", response_model=CartRead)
async def read_cart(db: DbSession, actor: ShopperDep) -> CartRead:
    return await cart_service.get_cart(db, actor)


@router.post("/items", response_model=CartRead)
@limiter.limit(settings.rate_limit_cart_writes)
async def add_item(
    request: Request,
    db: DbSession,
    actor: ShopperDep,
    payload: CartItemCreate,
) -> CartRead:
    del request
    return await cart_service.add_item(db, actor, payload.product_id, payload.quantity)


@router.patch("/items/{item_id}", response_model=CartRead)
@limiter.limit(settings.rate_limit_cart_writes)
async def set_quantity(
    request: Request,
    db: DbSession,
    actor: ShopperDep,
    item_id: uuid.UUID,
    payload: CartItemUpdate,
) -> CartRead:
    del request
    return await cart_service.set_quantity(db, actor, item_id, payload.quantity)


@router.delete("/items/{item_id}", response_model=CartRead)
@limiter.limit(settings.rate_limit_cart_writes)
async def remove_item(
    request: Request,
    db: DbSession,
    actor: ShopperDep,
    item_id: uuid.UUID,
) -> CartRead:
    del request
    return await cart_service.remove_item(db, actor, item_id)


@router.delete("", response_model=CartRead)
@limiter.limit(settings.rate_limit_cart_writes)
async def clear_cart(request: Request, db: DbSession, actor: ShopperDep) -> CartRead:
    del request
    return await cart_service.clear_cart(db, actor)
