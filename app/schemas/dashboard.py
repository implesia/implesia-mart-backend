import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DashboardRange = Literal["today", "yesterday", "7d", "30d", "this-month", "last-month", "custom"]
DashboardGrain = Literal["hour", "day", "week", "month"]
TrendDirection = Literal["up", "down", "flat", "new"]


class DashboardTrend(BaseModel):
    direction: TrendDirection
    text: str


class DashboardMetric(BaseModel):
    value: int
    display: str
    trend: DashboardTrend
    sparkline: list[int] = Field(default_factory=list)


class DashboardPoint(BaseModel):
    label: str
    revenue: int
    orders: int
    previous_revenue: int


class DashboardStatusSlice(BaseModel):
    status: str
    count: int
    share: float


class DashboardSeller(BaseModel):
    product_id: uuid.UUID | None
    slug: str
    title: str
    image_src: str
    category: str
    units: int
    revenue: int
    stock_label: str


class DashboardArea(BaseModel):
    name: str
    orders: int
    revenue: int
    share: float


class DashboardCategory(BaseModel):
    id: str
    label: str
    revenue: int
    units: int
    share: float


class DashboardRecentOrder(BaseModel):
    id: uuid.UUID
    number: str
    created_at: datetime
    status: str
    customer_name: str
    items_label: str
    total: int
    payment_method: str


class DashboardOverview(BaseModel):
    range: DashboardRange
    period_label: str
    comparison_label: str
    grain: DashboardGrain
    grain_label: str
    revenue: DashboardMetric
    orders: DashboardMetric
    customers: DashboardMetric
    average_order: DashboardMetric
    pending: DashboardMetric
    delivered: DashboardMetric
    series: list[DashboardPoint]
    statuses: list[DashboardStatusSlice]
    order_count: int
    best_sellers: list[DashboardSeller]
    recent: list[DashboardRecentOrder]
    areas: list[DashboardArea]
    categories: list[DashboardCategory]
