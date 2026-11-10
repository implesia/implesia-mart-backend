import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.deps import CurrentUser, DbSession, RequireEditor, no_store, require_editor
from app.schemas.order import (
    AdminOrderList,
    AdminOrderQuery,
    NewOrderFeed,
    NewOrderQuery,
    OrderRead,
    OrderUpdate,
)
from app.services import order_service

router = APIRouter(dependencies=[Depends(no_store), Depends(require_editor)])
# Any signed-in staff, including viewer. Registered beside the editor router so
# `/new` is not treated as an order id.
feed_router = APIRouter(dependencies=[Depends(no_store)])


@feed_router.get("/new", response_model=NewOrderFeed)
async def list_new_orders(
    db: DbSession,
    user: CurrentUser,
    query: Annotated[NewOrderQuery, Depends()],
) -> NewOrderFeed:
    del user
    return await order_service.list_new_orders(db, query)


@router.get("", response_model=AdminOrderList)
async def list_orders(
    db: DbSession,
    query: Annotated[AdminOrderQuery, Depends()],
) -> AdminOrderList:
    return await order_service.list_orders(db, query)


@router.get("/{order_id}", response_model=OrderRead)
async def read_order(db: DbSession, order_id: uuid.UUID) -> OrderRead:
    return await order_service.get_order(db, order_id)


@router.patch("/{order_id}", response_model=OrderRead)
async def update_order(
    db: DbSession,
    actor: RequireEditor,
    order_id: uuid.UUID,
    payload: OrderUpdate,
    background: BackgroundTasks,
) -> OrderRead:
    return await order_service.update_order(
        db, order_id, payload, actor=actor, background=background
    )
