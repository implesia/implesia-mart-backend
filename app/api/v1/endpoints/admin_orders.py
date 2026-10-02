import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.order import AdminOrderList, AdminOrderQuery, OrderRead, OrderUpdate
from app.services import order_service

router = APIRouter(dependencies=[Depends(no_store), Depends(require_editor)])


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
    order_id: uuid.UUID,
    payload: OrderUpdate,
) -> OrderRead:
    return await order_service.update_order(db, order_id, payload)
