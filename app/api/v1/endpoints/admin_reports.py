"""Read-only admin reports. Any signed-in staff member may call them."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession, no_store
from app.schemas.report import (
    ChannelBreakdownReport,
    CouponReport,
    DeliveryReport,
    MovementReport,
    OrderOriginFilter,
    ProductReport,
    ProductReportSort,
    ProfitFilter,
    ProfitLossReport,
    ProfitReport,
    ReportGrain,
    ReportPreset,
    SalesSummary,
    StockReport,
    SupplierPerformanceReport,
    TrendReport,
)
from app.services import report_service
from app.services.report_service import ReportRequest

router = APIRouter(dependencies=[Depends(no_store)])
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _request(
    preset: Annotated[ReportPreset | None, Query()] = None,
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
    product_id: Annotated[uuid.UUID | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    supplier_id: Annotated[uuid.UUID | None, Query()] = None,
    channel: Annotated[str | None, Query(max_length=32)] = None,
    origin: Annotated[OrderOriginFilter | None, Query()] = None,
    profit_filter: Annotated[ProfitFilter | None, Query()] = None,
    grain: Annotated[ReportGrain | None, Query()] = None,
    sort: Annotated[ProductReportSort | None, Query()] = None,
) -> ReportRequest:
    return ReportRequest(
        preset=preset,
        date_from=start,
        date_to=end,
        product_id=product_id,
        category_id=category_id,
        supplier_id=supplier_id,
        channel=channel,
        origin=origin,
        profit_filter=profit_filter,
        grain=grain,
        sort=sort,
    )


ReportArgs = Annotated[ReportRequest, Depends(_request)]


def _xlsx(name: str, payload: bytes) -> StreamingResponse:
    return StreamingResponse(
        iter([payload]),
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/sales", response_model=SalesSummary)
async def read_sales(user: CurrentUser, db: DbSession, request: ReportArgs) -> SalesSummary:
    del user
    return await report_service.sales_summary(db, request)


@router.get("/sales/export")
async def export_sales(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.sales_workbook(db, request)
    return _xlsx(name, payload)


@router.get("/profit", response_model=ProfitReport)
async def read_profit(user: CurrentUser, db: DbSession, request: ReportArgs) -> ProfitReport:
    del user
    return await report_service.profit_report(db, request)


@router.get("/profit/export")
async def export_profit(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.profit_workbook(db, request)
    return _xlsx(name, payload)


@router.get("/profit-loss", response_model=ProfitLossReport)
async def read_profit_loss(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> ProfitLossReport:
    del user
    return await report_service.profit_loss_report(db, request)


@router.get("/profit-loss/export")
async def export_profit_loss(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.profit_loss_workbook(db, request)
    return _xlsx(name, payload)


@router.get("/products", response_model=ProductReport)
async def read_products(
    user: CurrentUser,
    db: DbSession,
    request: ReportArgs,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ProductReport:
    del user
    return await report_service.product_report(
        db, request, page=page, page_size=page_size
    )


@router.get("/products/export")
async def export_products(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.product_workbook(db, request)
    return _xlsx(name, payload)


@router.get("/channels", response_model=ChannelBreakdownReport)
async def read_channels(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> ChannelBreakdownReport:
    del user
    return await report_service.channel_report(db, request)


@router.get("/channels/export")
async def export_channels(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.channel_workbook(db, request)
    return _xlsx(name, payload)


@router.get("/suppliers", response_model=SupplierPerformanceReport)
async def read_suppliers(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> SupplierPerformanceReport:
    del user
    return await report_service.supplier_report(db, request)


@router.get("/suppliers/export")
async def export_suppliers(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.supplier_workbook(db, request)
    return _xlsx(name, payload)


@router.get("/stock", response_model=StockReport)
async def read_stock(
    user: CurrentUser,
    db: DbSession,
    request: ReportArgs,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> StockReport:
    del user
    return await report_service.stock_report(db, request, page=page, page_size=page_size)


@router.get("/stock/export")
async def export_stock(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.stock_workbook(db, request)
    return _xlsx(name, payload)


@router.get("/movements", response_model=MovementReport)
async def read_movements(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> MovementReport:
    del user
    return await report_service.movement_report(db, request)


@router.get("/movements/export")
async def export_movements(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.movement_workbook(db, request)
    return _xlsx(name, payload)


@router.get("/delivery", response_model=DeliveryReport)
async def read_delivery(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> DeliveryReport:
    del user
    return await report_service.delivery_report(db, request)


@router.get("/delivery/export")
async def export_delivery(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.delivery_workbook(db, request)
    return _xlsx(name, payload)


@router.get("/trend", response_model=TrendReport)
async def read_trend(user: CurrentUser, db: DbSession, request: ReportArgs) -> TrendReport:
    del user
    return await report_service.trend_report(db, request)


@router.get("/trend/export")
async def export_trend(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.trend_workbook(db, request)
    return _xlsx(name, payload)


@router.get("/coupons", response_model=CouponReport)
async def read_coupons(user: CurrentUser, db: DbSession, request: ReportArgs) -> CouponReport:
    del user
    return await report_service.coupon_report(db, request)


@router.get("/coupons/export")
async def export_coupons(
    user: CurrentUser, db: DbSession, request: ReportArgs
) -> StreamingResponse:
    del user
    name, payload = await report_service.coupon_workbook(db, request)
    return _xlsx(name, payload)
