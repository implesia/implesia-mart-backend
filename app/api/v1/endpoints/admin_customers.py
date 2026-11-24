"""Admin customer report by phone, and the live courier check."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import DbSession, no_store, require_module_access
from app.core.config import settings
from app.rate_limit import courier_check_account_key, limiter
from app.schemas.customer_report import CourierCheck, CustomerReport
from app.services import customer_report_service

router = APIRouter(
    dependencies=[
        Depends(no_store),
        Depends(require_module_access("orders", "read")),
    ]
)


@router.get("/report", response_model=CustomerReport)
async def customer_phone_report(
    db: DbSession,
    phone: Annotated[str, Query(min_length=1, max_length=40)],
) -> CustomerReport:
    return await customer_report_service.customer_report(db, phone)


@router.post("/report/courier-check", response_model=CourierCheck)
@limiter.limit(settings.rate_limit_courier_check)
@limiter.limit(settings.rate_limit_courier_check, key_func=courier_check_account_key)
async def refresh_customer_courier_check(
    request: Request,
    db: DbSession,
    phone: Annotated[str, Query(min_length=1, max_length=40)],
) -> CourierCheck:
    del request
    return await customer_report_service.refresh_courier(db, phone)
