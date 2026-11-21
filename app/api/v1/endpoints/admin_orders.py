import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, Request

from app.api.deps import (
    CurrentUser,
    DbSession,
    RequireEditor,
    RequireSuperadmin,
    no_store,
    require_editor,
)
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.order import (
    AdminOrderList,
    AdminOrderQuery,
    BulkStatusRequest,
    BulkStatusResult,
    CustomerSearch,
    CustomerSearchQuery,
    NewOrderFeed,
    NewOrderQuery,
    OfflineOrderCreate,
    OrderDeleteImpact,
    OrderDeleteRequest,
    OrderDeleteResult,
    OrderIdList,
    OrderItemsUpdate,
    OrderOverview,
    OrderPaymentCreate,
    OrderRead,
    OrderUpdate,
    PrintData,
    PrintedResult,
)
from app.services import order_admin_service, order_service

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


@router.get("/overview", response_model=OrderOverview)
async def order_overview(db: DbSession) -> OrderOverview:
    return await order_admin_service.overview(db)


@router.get("/customers", response_model=CustomerSearch)
async def search_customers(
    db: DbSession,
    query: Annotated[CustomerSearchQuery, Depends()],
) -> CustomerSearch:
    return await order_admin_service.search_customers(db, query.q)


@router.get("/ready-to-pack", response_model=AdminOrderList)
async def ready_to_pack(
    db: DbSession,
    query: Annotated[AdminOrderQuery, Depends()],
) -> AdminOrderList:
    return await order_admin_service.ready_to_pack(db, query)


@router.post("/offline", response_model=OrderRead, status_code=201)
@limiter.limit(settings.rate_limit_product_writes)
async def create_offline_order(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    payload: OfflineOrderCreate,
    background: BackgroundTasks,
    idempotency_key: Annotated[str, Header()],
) -> OrderRead:
    del request
    return await order_admin_service.create_offline(
        db, payload, actor=actor, idempotency_key=idempotency_key, background=background
    )


@router.post("/bulk-status", response_model=BulkStatusResult)
@limiter.limit(settings.rate_limit_product_writes)
async def bulk_status(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    payload: BulkStatusRequest,
    background: BackgroundTasks,
) -> BulkStatusResult:
    del request
    return await order_admin_service.bulk_status(
        db, payload, actor=actor, background=background
    )


@router.post("/printed", response_model=PrintedResult)
@limiter.limit(settings.rate_limit_product_writes)
async def mark_printed(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    payload: OrderIdList,
) -> PrintedResult:
    del request
    return await order_admin_service.mark_printed(db, payload.ids, actor=actor)


@router.post("/print-data", response_model=PrintData)
@limiter.limit(settings.rate_limit_product_writes)
async def print_data(request: Request, db: DbSession, payload: OrderIdList) -> PrintData:
    del request
    return await order_admin_service.print_data(db, payload.ids)


@router.get("", response_model=AdminOrderList)
async def list_orders(
    db: DbSession,
    query: Annotated[AdminOrderQuery, Depends()],
) -> AdminOrderList:
    return await order_service.list_orders(db, query)


@router.get("/{order_id}/delete-impact", response_model=OrderDeleteImpact)
async def order_delete_impact(
    db: DbSession,
    actor: RequireSuperadmin,
    order_id: uuid.UUID,
) -> OrderDeleteImpact:
    del actor
    return await order_admin_service.delete_impact(db, order_id)


@router.delete("/{order_id}", response_model=OrderDeleteResult)
@limiter.limit(settings.rate_limit_product_writes)
async def delete_order(
    request: Request,
    db: DbSession,
    actor: RequireSuperadmin,
    order_id: uuid.UUID,
    payload: OrderDeleteRequest = Body(...),
) -> OrderDeleteResult:
    del request
    return await order_admin_service.delete_order(db, order_id, payload, actor=actor)


@router.get("/{order_id}", response_model=OrderRead)
async def read_order(db: DbSession, order_id: uuid.UUID) -> OrderRead:
    return await order_service.get_order(db, order_id)


@router.patch("/{order_id}", response_model=OrderRead)
@limiter.limit(settings.rate_limit_product_writes)
async def update_order(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    order_id: uuid.UUID,
    payload: OrderUpdate,
    background: BackgroundTasks,
) -> OrderRead:
    del request
    return await order_service.update_order(
        db, order_id, payload, actor=actor, background=background
    )


@router.put("/{order_id}/items", response_model=OrderRead)
@limiter.limit(settings.rate_limit_product_writes)
async def replace_order_items(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    order_id: uuid.UUID,
    payload: OrderItemsUpdate,
    background: BackgroundTasks,
) -> OrderRead:
    del request
    return await order_admin_service.replace_items(
        db, order_id, payload, actor=actor, background=background
    )


@router.post("/{order_id}/payments", response_model=OrderRead)
@limiter.limit(settings.rate_limit_product_writes)
async def record_order_payment(
    request: Request,
    db: DbSession,
    actor: RequireEditor,
    order_id: uuid.UUID,
    payload: OrderPaymentCreate,
) -> OrderRead:
    del request
    return await order_admin_service.record_payment(db, order_id, payload, actor=actor)
