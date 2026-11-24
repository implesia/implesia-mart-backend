import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CourierProviderStatus = Literal["not_configured", "ok", "error", "unverified"]
RiskLevel = Literal["unknown", "low", "medium", "high"]


class CustomerBrief(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None = None


class StatusCounts(BaseModel):
    new: int = 0
    confirmed: int = 0
    packed: int = 0
    shipped: int = 0
    delivered: int = 0
    cancelled: int = 0
    returned: int = 0


class CustomerReportSummary(BaseModel):
    total_orders: int
    by_status: StatusCounts
    delivered_count: int
    cancelled_count: int
    returned_count: int
    success_rate: float | None
    total_spent: int
    first_order_at: datetime | None
    last_order_at: datetime | None
    online_count: int
    offline_count: int


class ReportOrder(BaseModel):
    id: uuid.UUID
    number: str
    status: str
    origin: str
    total: int
    created_at: datetime
    tracking_number: str


class CourierProviderResult(BaseModel):
    provider: str
    status: CourierProviderStatus
    total_parcels: int | None = None
    delivered: int | None = None
    returned_or_cancelled: int | None = None
    success_rate: float | None = None
    error_message: str | None = None


class CourierTotals(BaseModel):
    total_parcels: int = 0
    delivered: int = 0
    returned_or_cancelled: int = 0
    success_rate: float | None = None


class CourierCheck(BaseModel):
    enabled: bool
    checked_at: datetime | None
    stale: bool
    totals: CourierTotals
    risk_level: RiskLevel
    providers: list[CourierProviderResult]


class CustomerReport(BaseModel):
    phone: str
    customer: CustomerBrief | None
    summary: CustomerReportSummary
    orders: list[ReportOrder] = Field(default_factory=list)
    courier_check: CourierCheck
