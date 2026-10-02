import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.cart import AdminCartList, AdminCartQuery, AdminCartRead
from app.services import cart_service

router = APIRouter(dependencies=[Depends(no_store), Depends(require_editor)])


@router.get("", response_model=AdminCartList)
async def list_carts(
    db: DbSession,
    query: Annotated[AdminCartQuery, Depends()],
) -> AdminCartList:
    return await cart_service.list_carts(db, query)


@router.get("/{cart_id}", response_model=AdminCartRead)
async def read_cart(db: DbSession, cart_id: uuid.UUID) -> AdminCartRead:
    return await cart_service.get_admin_cart(db, cart_id)
