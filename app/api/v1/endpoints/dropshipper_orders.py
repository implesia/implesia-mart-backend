"""Dropshipper order, tracking, fraud-check, wallet, payout & top-up endpoints."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Query, Request, status

from app.api.deps import DbSession, RequireApprovedDropshipper, no_store
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.customer_report import CourierCheck
from app.schemas.dropshipping import (
    DropshipOrderCreateRequest,
    DropshipOrderDetail,
    DropshipOrderListResponse,
    DropshipOrderQuoteRequest,
    DropshipOrderQuoteResponse,
    DropshipOrderTrackingResponse,
    DropshipperPayoutCreateRequest,
    DropshipperPayoutListResponse,
    DropshipperPayoutRead,
    DropshipperTopupCreateRequest,
    DropshipperTopupListResponse,
    DropshipperTopupRead,
    DropshipperWalletSummary,
    DropshipperWalletTransactionListResponse,
)
from app.services import dropship_order_service, dropship_wallet_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.post("/orders/quote", response_model=DropshipOrderQuoteResponse)
async def quote_dropship_order(
    payload: DropshipOrderQuoteRequest,
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipOrderQuoteResponse:
    return await dropship_order_service.quote_order(db, user, payload)


@router.post("/orders", response_model=DropshipOrderDetail, status_code=status.HTTP_201_CREATED)
async def create_dropship_order(
    payload: DropshipOrderCreateRequest,
    db: DbSession,
    user: RequireApprovedDropshipper,
    background: BackgroundTasks,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")] = "",
) -> DropshipOrderDetail:
    return await dropship_order_service.create_order(
        db,
        user,
        payload,
        idempotency_key=idempotency_key,
        background=background,
    )


@router.get("/orders", response_model=DropshipOrderListResponse)
async def list_dropship_orders(
    db: DbSession,
    user: RequireApprovedDropshipper,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DropshipOrderListResponse:
    return await dropship_order_service.list_orders(
        db, user, status=status_filter, q=q, page=page, page_size=page_size
    )


@router.get("/orders/{order_number}", response_model=DropshipOrderDetail)
async def get_dropship_order(
    order_number: str,
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipOrderDetail:
    return await dropship_order_service.get_order(db, user, order_number)


@router.get("/orders/{order_number}/tracking", response_model=DropshipOrderTrackingResponse)
async def get_dropship_order_tracking(
    order_number: str,
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipOrderTrackingResponse:
    return await dropship_order_service.get_order_tracking(db, user, order_number)


@router.get("/fraud-check", response_model=CourierCheck)
@limiter.limit(settings.rate_limit_courier_check)
async def dropshipper_fraud_check(
    request: Request,
    db: DbSession,
    user: RequireApprovedDropshipper,
    phone: Annotated[str, Query(min_length=6, max_length=40)],
    refresh: bool = Query(default=False),
) -> CourierCheck:
    del request, user
    return await dropship_order_service.fraud_check(db, phone, refresh=refresh)


@router.get("/wallet", response_model=DropshipperWalletSummary)
async def get_dropshipper_wallet(
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipperWalletSummary:
    return await dropship_wallet_service.get_wallet_summary(db, user)


@router.get("/wallet/transactions", response_model=DropshipperWalletTransactionListResponse)
async def list_dropshipper_wallet_transactions(
    db: DbSession,
    user: RequireApprovedDropshipper,
    entry_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DropshipperWalletTransactionListResponse:
    return await dropship_wallet_service.list_wallet_transactions(
        db, user, entry_type=entry_type, page=page, page_size=page_size
    )


@router.post("/payouts", response_model=DropshipperPayoutRead, status_code=status.HTTP_201_CREATED)
async def create_dropshipper_payout(
    payload: DropshipperPayoutCreateRequest,
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipperPayoutRead:
    return await dropship_wallet_service.create_payout_request(db, user, payload)


@router.get("/payouts", response_model=DropshipperPayoutListResponse)
async def list_dropshipper_payouts(
    db: DbSession,
    user: RequireApprovedDropshipper,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DropshipperPayoutListResponse:
    return await dropship_wallet_service.list_my_payouts(db, user, page=page, page_size=page_size)


@router.post("/topups", response_model=DropshipperTopupRead, status_code=status.HTTP_201_CREATED)
async def create_dropshipper_topup(
    payload: DropshipperTopupCreateRequest,
    db: DbSession,
    user: RequireApprovedDropshipper,
) -> DropshipperTopupRead:
    return await dropship_wallet_service.create_topup_request(db, user, payload)


@router.get("/topups", response_model=DropshipperTopupListResponse)
async def list_dropshipper_topups(
    db: DbSession,
    user: RequireApprovedDropshipper,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DropshipperTopupListResponse:
    return await dropship_wallet_service.list_my_topups(db, user, page=page, page_size=page_size)
