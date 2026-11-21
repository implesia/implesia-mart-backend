"""Admin report responses. Cost figures stay on these models only."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.schemas.inventory import MovementRead

ReportPreset = Literal[
    "today",
    "7d",
    "this_week",
    "this_month",
    "last_month",
    "this_year",
]
ReportGrain = Literal["day", "week", "month"]
OrderOriginFilter = Literal["online", "offline"]
ProfitFilter = Literal["all", "profit", "loss", "unknown_cost"]
ProductReportSort = Literal[
    "revenue",
    "profit",
    "margin",
    "units_sold",
    "cost",
    "stock_value",
]


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
    supplier_id: uuid.UUID | None = None
    channel: str | None = None
    origin: OrderOriginFilter | None = None
    profit_filter: ProfitFilter | None = None
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
    # Coupon taka only. Staff manual_discount is exposed separately in manual_discount.
    # A product or category filter keeps that filter's share of the coupon.
    # NULL coupon columns count as 0, so orders from before coupons are unchanged.
    coupon_discount: int
    # Staff manual_discount taka only (0 on checkout orders).
    # A product or category filter keeps that filter's share of manual_discount.
    manual_discount: int = 0
    # Sum of orders.shipping, once per realized delivered order. A product filter still
    # counts the whole order's delivery charge, not a share of it.
    # Free delivery is already shipping 0 on the order.
    delivery_charge: int
    # gross_sales - discount + delivery_charge. Whole taka. Net of coupon and staff discount.
    net_sales: int


class ProfitReport(BaseModel):
    filters: ReportFilters
    # line_total of lines that have a unit_cost, minus that line's share of
    # the coupon and manual_discount. Delivery is not included.
    revenue: int
    cost: ReportMoney | None = None
    profit: ReportMoney | None = None
    # Sum of absolute loss across realized known-cost lines sold below cost.
    loss_amount: ReportMoney = Decimal("0.00")
    net_profit: ReportMoney | None = None
    margin_percent: ReportMoney | None = None
    unknown_cost_lines: int
    unknown_cost_units: int
    unknown_cost_revenue: int


class ProfitLossReport(BaseModel):
    """Full P&L waterfall across realized delivered orders, returns, COGS, and collections."""

    filters: ReportFilters
    gross_sales: int
    product_discount: int
    coupon_discount: int
    manual_discount: int
    delivery_charge: int
    returned_order_value: int
    net_realized_sales: int
    total_cost: ReportMoney | None = None
    gross_profit: ReportMoney | None = None
    # Sum of absolute losses on realized negative-margin lines.
    loss_amount: ReportMoney = Decimal("0.00")
    net_profit: ReportMoney | None = None
    margin_percent: ReportMoney | None = None
    collected_amount: int
    due_amount: int
    unknown_cost_lines: int
    unknown_cost_units: int
    unknown_cost_revenue: int


class ProductReportRow(BaseModel):
    product_id: uuid.UUID | None
    title: str
    slug: str = ""
    sku: str = ""
    category_name: str = ""
    supplier_id: uuid.UUID | None = None
    supplier_name: str | None = None
    units_sold: int
    avg_selling_price: ReportMoney | None = None
    unit_cost_avg: ReportMoney | None = None
    current_cost_price: ReportMoney | None = None
    current_stock: int | None = None
    stock_value: ReportMoney | None = None
    revenue: int
    cost: ReportMoney | None = None
    profit: ReportMoney | None = None
    is_loss: bool = False
    margin_percent: ReportMoney | None = None
    # Distinct orders with returned_at in the window that include this product.
    return_count: int
    # Sum of OrderItem.quantity across returned orders in the window for this product.
    returned_units: int = 0
    # Sum of line_total across returned orders in the window for this product.
    return_value: int = 0
    unknown_cost_units: int


class ProductReport(BaseModel):
    filters: ReportFilters
    sort: ProductReportSort = "revenue"
    items: list[ProductReportRow]
    total: int
    page: int
    page_size: int
    pages: int


class ChannelBreakdownRow(BaseModel):
    origin: OrderOriginFilter
    channel: str
    order_count: int
    units: int
    net_sales: int
    cogs: ReportMoney | None = None
    profit: ReportMoney | None = None
    margin_percent: ReportMoney | None = None
    collected: int
    due: int
    unknown_cost_units: int = 0


class PaymentMethodBreakdownRow(BaseModel):
    payment_method: str
    order_count: int
    units: int
    net_sales: int
    cogs: ReportMoney | None = None
    profit: ReportMoney | None = None
    margin_percent: ReportMoney | None = None
    collected: int
    due: int
    unknown_cost_units: int = 0


class ChannelBreakdownReport(BaseModel):
    filters: ReportFilters
    channels: list[ChannelBreakdownRow]
    payment_methods: list[PaymentMethodBreakdownRow]


class SupplierPerformanceRow(BaseModel):
    supplier_id: uuid.UUID
    supplier_name: str
    linked_products_count: int
    purchase_count: int
    total_purchased_units: int
    total_purchase_spend: ReportMoney
    units_sold: int
    sales_revenue: int
    cogs: ReportMoney | None = None
    net_profit: ReportMoney | None = None
    margin_percent: ReportMoney | None = None
    current_stock_units: int
    current_stock_value: ReportMoney
    unknown_cost_units: int = 0


class SupplierPerformanceReport(BaseModel):
    filters: ReportFilters
    items: list[SupplierPerformanceRow]
    total_purchase_spend: ReportMoney
    total_sales_revenue: int
    total_cogs: ReportMoney | None = None
    total_net_profit: ReportMoney | None = None


class StockSummary(BaseModel):
    product_count: int
    units_on_hand: int
    # Sum of quantity × cost_price where both are set. Missing costs are not guessed.
    stock_value: ReportMoney
    potential_retail_value: ReportMoney = Decimal("0.00")
    expected_profit_on_hand: ReportMoney = Decimal("0.00")
    missing_cost_count: int = 0
    unknown_cost_units: int
    low_stock_count: int
    low_stock_at: int
    no_sale_30d_count: int


class StockRow(BaseModel):
    product_id: uuid.UUID
    title: str
    quantity: int | None
    selling_price: int = 0
    cost_price: ReportMoney | None = None
    stock_value: ReportMoney | None = None
    potential_retail_value: ReportMoney | None = None
    expected_profit_on_hand: ReportMoney | None = None
    supplier_name: str | None = None
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
    # Total order value (sum of orders.total) of returned orders in the window.
    returned_value: int = 0
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


class ProductAnalyticsPeriod(BaseModel):
    units_sold: int
    revenue: int
    cogs: ReportMoney | None = None
    profit: ReportMoney | None = None
    is_loss: bool = False
    margin_percent: ReportMoney | None = None
    return_count: int
    returned_units: int = 0
    unknown_cost_units: int = 0


class ProductAnalyticsReport(BaseModel):
    product_id: uuid.UUID
    title: str
    slug: str
    supplier_id: uuid.UUID | None = None
    supplier_name: str | None = None
    current_stock: int | None = None
    current_cost_price: ReportMoney | None = None
    selling_price: int
    current_stock_value: ReportMoney | None = None
    potential_retail_value: ReportMoney | None = None
    lifetime: ProductAnalyticsPeriod
    last_30_days: ProductAnalyticsPeriod
    recent_movements: list[MovementRead]
