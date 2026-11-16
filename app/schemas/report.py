"""Admin report responses. Cost figures stay on these models only."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

ReportPreset = Literal["this_week", "this_month", "last_month"]
ReportGrain = Literal["day", "week", "month"]


def _money_json(value: Decimal) -> float:
    return float(value)


# Two-decimal taka. JSON is a number so a client can add the column.
ReportMoney = Annotated[
    Decimal,
    PlainSerializer(_money_json, return_type=float, when_used="json"),
]


class ReportFilters(BaseModel):
    """The window the report used. Dates are inclusive Asia/Dhaka calendar days."""

    model_config = ConfigDict(populate_by_name=True)

    timezone: Literal["Asia/Dhaka"] = "Asia/Dhaka"
    preset: str | None = None
    date_from: date = Field(alias="from")
    date_to: date = Field(alias="to")
    product_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    channel: str | None = None
    # Stock on hand and the ledger have no channel. Sales reports use it.
    channel_applies: bool = True


class SalesSummary(BaseModel):
    filters: ReportFilters
    order_count: int
    units_sold: int
    # Sum of list price × quantity (regular price, or the selling price when
    # the line has no regular price). Whole taka.
    gross_sales: int
    # List-price discount, quantity discount, coupon, and staff manual_discount.
    # gross_sales - the sum of line totals, plus those order discounts.
    discount: int
    # Coupon taka only. Staff manual_discount is in discount and not here.
    # A product or category filter keeps that filter's share of the coupon.
    # NULL coupon columns count as 0, so orders from before coupons are unchanged.
    coupon_discount: int
    # Sum of orders.shipping, once per delivered order. A product filter still
    # counts the whole order's delivery charge, not a share of it.
    # Free delivery is already shipping 0 on the order.
    delivery_charge: int
    # gross_sales - discount + delivery_charge. Whole taka. Net of coupon and staff discount.
    net_sales: int


class ProfitReport(BaseModel):
    filters: ReportFilters
    # line_total of lines that have a unit_cost, minus that line's share of
    # the coupon. Delivery is not included.
    revenue: int
    cost: ReportMoney | None = None
    profit: ReportMoney | None = None
    margin_percent: ReportMoney | None = None
    unknown_cost_lines: int
    unknown_cost_units: int
    unknown_cost_revenue: int


class ProductReportRow(BaseModel):
    product_id: uuid.UUID | None
    title: str
    units_sold: int
    revenue: int
    cost: ReportMoney | None = None
    profit: ReportMoney | None = None
    margin_percent: ReportMoney | None = None
    # Distinct orders with returned_at in the window that include this product.
    return_count: int
    unknown_cost_units: int


class ProductReport(BaseModel):
    filters: ReportFilters
    items: list[ProductReportRow]
    total: int
    page: int
    page_size: int
    pages: int


class StockSummary(BaseModel):
    product_count: int
    units_on_hand: int
    # Sum of quantity × cost_price where both are set. Missing costs are not guessed.
    stock_value: ReportMoney
    unknown_cost_units: int
    low_stock_count: int
    low_stock_at: int
    no_sale_30d_count: int


class StockRow(BaseModel):
    product_id: uuid.UUID
    title: str
    quantity: int | None
    cost_price: ReportMoney | None = None
    stock_value: ReportMoney | None = None
    low_stock: bool
    no_sale_30d: bool


class StockReport(BaseModel):
    filters: ReportFilters
    # On-hand figures ignore the date window. They are the stock right now.
    period_applies: bool = False
    as_of: date
    no_sale_since: date
    summary: StockSummary
    items: list[StockRow]
    total: int
    page: int
    page_size: int
    pages: int


class MovementReport(BaseModel):
    """Signed ledger totals. A sale is negative. closing = opening_balance + the six totals."""

    model_config = ConfigDict(populate_by_name=True)

    filters: ReportFilters
    opening_balance: int
    opening: int
    purchase: int
    sale: int
    return_total: int = Field(alias="return")
    cancel: int
    adjustment: int
    closing: int


class DeliveryReport(BaseModel):
    filters: ReportFilters
    delivered: int
    returned: int
    cancelled: int
    # returned / delivered × 100. Null when nothing was delivered in the window.
    return_rate_percent: ReportMoney | None = None


class TrendPoint(BaseModel):
    start: date
    net_sales: int
    profit: ReportMoney | None = None
    unknown_cost_revenue: int


class TrendReport(BaseModel):
    filters: ReportFilters
    grain: ReportGrain
    points: list[TrendPoint]


class CouponReportRow(BaseModel):
    coupon_id: uuid.UUID
    code: str
    times_used: int
    total_discount: int
    # Sum of orders.total (after the coupon, including delivery) for those uses.
    total_sales: int


class CouponReport(BaseModel):
    """Active redemptions whose order was placed in the window. Cancelled uses are omitted.

    A returned order stays in the count. The date is the redemption time, which
    is the order time, not delivered_at.
    """

    filters: ReportFilters
    items: list[CouponReportRow]
    times_used: int
    total_discount: int
    total_sales: int
