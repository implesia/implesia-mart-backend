"""Admin sales, profit, P&L, channel, supplier, stock, and delivery reports.

Every total is a SQL aggregate. Python only applies a ratio (margin, return
rate, net = gross − discount + delivery) to those totals, and fills empty
chart buckets. Order rows are never loaded.

Dates are inclusive Asia/Dhaka calendar days. A sale counts on delivered_at.
A return counts on returned_at. A cancellation counts on updated_at, because
there is no cancelled_at column. Lines with no unit_cost are reported as
unknown cost and are not filled in from the product's current cost_price.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from typing import cast as typing_cast

from sqlalchemy import Float, Numeric, String, and_, case, cast, distinct, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.category import Category
from app.models.coupon import Coupon, CouponRedemption
from app.models.inventory import Purchase, PurchaseItem, StockMovement, Supplier
from app.models.order import Order, OrderItem, OrderOrigin, OrderStatus
from app.models.product import Product, ProductVariant
from app.schemas.common import page_count
from app.schemas.inventory import MovementQuery
from app.schemas.report import (
    ChannelBreakdownReport,
    ChannelBreakdownRow,
    CouponReport,
    CouponReportRow,
    DeliveryReport,
    MovementReport,
    OrderOriginFilter,
    PaymentMethodBreakdownRow,
    ProductAnalyticsPeriod,
    ProductAnalyticsReport,
    ProductReport,
    ProductReportRow,
    ProductReportSort,
    ProfitFilter,
    ProfitLossReport,
    ProfitReport,
    ReportFilters,
    ReportGrain,
    SalesSummary,
    StockReport,
    StockRow,
    StockSummary,
    SupplierPerformanceReport,
    SupplierPerformanceRow,
    TrendPoint,
    TrendReport,
)
from app.services import inventory_service, product_service
from app.services.category_service import load_index
from app.services.inventory_excel import MAX_EXPORT_ROWS, workbook_bytes
from app.services.shop_sql import SHOP, at_or_after, before, dhaka_day, dialect_name

PRESETS = ("today", "7d", "this_week", "this_month", "last_month", "this_year")
ORIGINS: tuple[OrderOriginFilter, ...] = ("online", "offline")
PROFIT_FILTERS: tuple[ProfitFilter, ...] = ("all", "profit", "loss", "unknown_cost")
PRODUCT_SORTS: tuple[ProductReportSort, ...] = (
    "revenue",
    "profit",
    "margin",
    "units_sold",
    "cost",
    "stock_value",
)
CANONICAL_PAYMENT_METHODS = ("cod", "bangla_qr", "cash", "bkash", "nagad", "card", "due")
LOW_STOCK_AT = 5
_TWOPLACES = Decimal("0.01")


@dataclass(frozen=True)
class ReportRequest:
    preset: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    product_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    channel: str | None = None
    origin: str | None = None
    profit_filter: str | None = None
    grain: str | None = None
    sort: str | None = None


@dataclass(frozen=True)
class ReportScope:
    start: datetime
    end: datetime
    date_from: date
    date_to: date
    preset: str | None
    product_id: uuid.UUID | None
    category_id: uuid.UUID | None
    category_ids: tuple[uuid.UUID, ...] | None
    supplier_id: uuid.UUID | None
    channel: str | None
    origin: OrderOriginFilter | None
    profit_filter: ProfitFilter | None

    def filters(self, *, channel_applies: bool = True) -> ReportFilters:
        return ReportFilters(
            preset=self.preset,
            date_from=self.date_from,
            date_to=self.date_to,
            product_id=self.product_id,
            category_id=self.category_id,
            supplier_id=self.supplier_id,
            channel=self.channel,
            origin=self.origin,
            profit_filter=self.profit_filter,
            channel_applies=channel_applies,
        )


@dataclass
class _LineTotals:
    units: int = 0
    gross: int = 0
    merchandise: int = 0
    known_revenue: int = 0
    cost: Decimal | None = None
    unknown_units: int = 0
    unknown_revenue: int = 0
    unknown_lines: int = 0


@dataclass
class _DayFigures:
    merchandise: int = 0
    delivery: int = 0
    known_revenue: int = 0
    cost: Decimal = field(default_factory=lambda: Decimal("0.00"))
    had_known: bool = False
    unknown_revenue: int = 0
    coupon: int = 0
    known_coupon: int = 0
    unknown_coupon: int = 0


@dataclass
class _CouponShares:
    matched: int = 0
    known: int = 0
    unknown: int = 0
    coupon_only: int = 0
    manual_only: int = 0


@dataclass
class _GroupTotals:
    order_count: int = 0
    shipping: int = 0
    collected: int = 0
    due: int = 0
    units: int = 0
    merchandise: int = 0
    known_merchandise: int = 0
    cost: Decimal | None = None
    unknown_units: int = 0
    matched_discount: int = 0
    known_discount: int = 0


def window_bounds(
    *,
    preset: str | None,
    date_from: date | None,
    date_to: date | None,
    now: datetime,
) -> tuple[str | None, date, date, datetime, datetime]:
    """Inclusive Dhaka dates plus the half-open [start, end) instants."""
    if preset is not None and (date_from is not None or date_to is not None):
        raise UnprocessableError("Choose a preset or a from and to date, not both")
    if preset is None and date_from is None and date_to is None:
        raise UnprocessableError("Choose a preset or a from and to date")
    if preset is not None:
        if preset not in PRESETS:
            raise UnprocessableError(
                "preset must be today, 7d, this_week, this_month, last_month, or this_year"
            )
        start_day, end_day = _preset_days(preset, now.astimezone(SHOP))
    else:
        if date_from is None or date_to is None:
            raise UnprocessableError("Choose both a from and a to date")
        if date_from > date_to:
            raise UnprocessableError("from is after to")
        start_day, end_day = date_from, date_to
    if (end_day - start_day).days + 1 > 366:
        raise UnprocessableError("Choose a range of 366 days or less")
    start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=SHOP)
    end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=SHOP) + timedelta(days=1)
    return preset, start_day, end_day, start, end


def _preset_days(preset: str, now: datetime) -> tuple[date, date]:
    today = now.astimezone(SHOP).date()
    if preset == "today":
        return today, today
    if preset == "7d":
        return today - timedelta(days=6), today
    if preset == "this_week":
        return today - timedelta(days=today.weekday()), today
    if preset == "this_month":
        return today.replace(day=1), today
    if preset == "this_year":
        return today.replace(month=1, day=1), today
    first_this_month = today.replace(day=1)
    last_previous = first_this_month - timedelta(days=1)
    return last_previous.replace(day=1), last_previous


def _parse_origin(raw: str | None) -> OrderOriginFilter | None:
    cleaned = (raw or "").strip().lower() or None
    if cleaned is None:
        return None
    if cleaned not in ORIGINS:
        raise UnprocessableError("origin must be online or offline")
    return typing_cast(OrderOriginFilter, cleaned)


def _parse_profit_filter(raw: str | None) -> ProfitFilter | None:
    cleaned = (raw or "").strip().lower() or None
    if cleaned is None:
        return None
    if cleaned not in PROFIT_FILTERS:
        raise UnprocessableError("profit_filter must be all, profit, loss, or unknown_cost")
    return typing_cast(ProfitFilter, cleaned)


def _parse_product_sort(raw: str | None) -> ProductReportSort:
    cleaned = (raw or "").strip().lower() or "revenue"
    if cleaned not in PRODUCT_SORTS:
        raise UnprocessableError(
            "sort must be revenue, profit, margin, units_sold, cost, or stock_value"
        )
    return typing_cast(ProductReportSort, cleaned)


async def _scope(db: AsyncSession, request: ReportRequest, now: datetime | None) -> ReportScope:
    moment = now if now is not None else datetime.now(SHOP)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHOP)
    preset, start_day, end_day, start, end = window_bounds(
        preset=request.preset,
        date_from=request.date_from,
        date_to=request.date_to,
        now=moment,
    )
    channel = (request.channel or "").strip() or None
    if channel is not None and len(channel) > 32:
        raise UnprocessableError("channel must be 32 characters or fewer")
    origin = _parse_origin(request.origin)
    profit_filter = _parse_profit_filter(request.profit_filter)
    category_ids: tuple[uuid.UUID, ...] | None = None
    if request.category_id is not None:
        index = await load_index(db)
        if request.category_id not in index.by_id:
            raise UnprocessableError("Category not found")
        category_ids = tuple(index.descendants(request.category_id))
    if request.product_id is not None:
        product = await db.get(Product, request.product_id)
        if product is None:
            raise UnprocessableError("Product not found")
    if request.supplier_id is not None:
        supplier = await db.get(Supplier, request.supplier_id)
        if supplier is None:
            raise UnprocessableError("Supplier not found")
    return ReportScope(
        start=start,
        end=end,
        date_from=start_day,
        date_to=end_day,
        preset=preset,
        product_id=request.product_id,
        category_id=request.category_id,
        category_ids=category_ids,
        supplier_id=request.supplier_id,
        channel=channel,
        origin=origin,
        profit_filter=profit_filter,
    )


def _matching_line(scope: ReportScope) -> Any | None:
    if scope.product_id is None and scope.category_ids is None and scope.supplier_id is None:
        return None
    stmt = select(OrderItem.id).where(OrderItem.order_id == Order.id)
    if scope.product_id is not None:
        stmt = stmt.where(OrderItem.product_id == scope.product_id)
    if scope.category_ids is not None or scope.supplier_id is not None:
        stmt = stmt.join(Product, Product.id == OrderItem.product_id)
        if scope.category_ids is not None:
            stmt = stmt.where(Product.category_id.in_(scope.category_ids))
        if scope.supplier_id is not None:
            stmt = stmt.where(Product.supplier_id == scope.supplier_id)
    return stmt.exists()


def _order_filters(scope: ReportScope, moment: Any, dialect: str, *extra: Any) -> list[Any]:
    conds: list[Any] = [
        at_or_after(moment, scope.start, dialect),
        before(moment, scope.end, dialect),
        *extra,
    ]
    if scope.channel is not None:
        conds.append(Order.channel == scope.channel)
    if scope.origin is not None:
        conds.append(Order.origin == scope.origin)
    matched = _matching_line(scope)
    if matched is not None:
        conds.append(matched)
    return conds


def _realized_order_cond() -> Any:
    """Returned orders do not count as realized sales, revenue, shipping, or COGS."""
    return Order.status != OrderStatus.RETURNED.value


def _effective_collected_expr() -> Any:
    """Collected taka on an order: explicit paid_amount, settled COD, or Bangla QR advance."""
    raw = case(
        (Order.paid_amount > 0, Order.paid_amount),
        (
            and_(
                Order.payment_method == "cod",
                Order.status == OrderStatus.DELIVERED.value,
            ),
            Order.total,
        ),
        (
            and_(
                Order.payment_method == "bangla_qr",
                Order.advance_amount > 0,
            ),
            Order.advance_amount,
        ),
        else_=0,
    )
    return case((raw > Order.total, Order.total), else_=raw)


def _effective_due_expr() -> Any:
    collected = _effective_collected_expr()
    return case((Order.total > collected, Order.total - collected), else_=0)


def _sql_num(dialect: str) -> Any:
    return Numeric(16, 4) if dialect == "postgresql" else Float


def _line_statement(scope: ReportScope, columns: Any, dialect: str) -> Any:
    stmt = (
        select(*columns)
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
    )
    conds: list[Any] = [
        at_or_after(Order.delivered_at, scope.start, dialect),
        before(Order.delivered_at, scope.end, dialect),
        _realized_order_cond(),
    ]
    if scope.channel is not None:
        conds.append(Order.channel == scope.channel)
    if scope.origin is not None:
        conds.append(Order.origin == scope.origin)
    if scope.product_id is not None:
        conds.append(OrderItem.product_id == scope.product_id)
    if scope.category_ids is not None:
        conds.append(Product.category_id.in_(scope.category_ids))
    if scope.supplier_id is not None:
        conds.append(Product.supplier_id == scope.supplier_id)
    return stmt.where(*conds)


async def _order_shipping(db: AsyncSession, scope: ReportScope) -> tuple[int, int]:
    count, shipping = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.shipping), 0))
            .select_from(Order)
            .where(
                *_order_filters(scope, Order.delivered_at, dialect_name(db), _realized_order_cond())
            )
        )
    ).one()
    return int(count), int(shipping)


async def _order_collections(db: AsyncSession, scope: ReportScope) -> tuple[int, int]:
    collected, due = (
        await db.execute(
            select(
                func.coalesce(func.sum(_effective_collected_expr()), 0),
                func.coalesce(func.sum(_effective_due_expr()), 0),
            )
            .select_from(Order)
            .where(
                *_order_filters(scope, Order.delivered_at, dialect_name(db), _realized_order_cond())
            )
        )
    ).one()
    return int(collected), int(due)


async def _returned_value(db: AsyncSession, scope: ReportScope) -> int:
    value = await db.scalar(
        select(func.coalesce(func.sum(Order.total), 0))
        .select_from(Order)
        .where(*_order_filters(scope, Order.returned_at, dialect_name(db)))
    )
    return int(value or 0)


async def _line_totals(db: AsyncSession, scope: ReportScope) -> _LineTotals:
    known = OrderItem.unit_cost.is_not(None)
    unknown = OrderItem.unit_cost.is_(None)
    list_price = func.coalesce(OrderItem.regular_price, OrderItem.unit_price)
    row = (
        await db.execute(
            _line_statement(
                scope,
                [
                    func.coalesce(func.sum(OrderItem.quantity), 0),
                    func.coalesce(func.sum(list_price * OrderItem.quantity), 0),
                    func.coalesce(func.sum(OrderItem.line_total), 0),
                    func.coalesce(func.sum(case((known, OrderItem.line_total), else_=0)), 0),
                    func.sum(case((known, OrderItem.quantity * OrderItem.unit_cost))),
                    func.coalesce(func.sum(case((unknown, OrderItem.quantity), else_=0)), 0),
                    func.coalesce(func.sum(case((unknown, OrderItem.line_total), else_=0)), 0),
                    func.coalesce(func.sum(case((unknown, 1), else_=0)), 0),
                ],
                dialect_name(db),
            )
        )
    ).one()
    return _LineTotals(
        units=int(row[0]),
        gross=int(row[1]),
        merchandise=int(row[2]),
        known_revenue=int(row[3]),
        cost=_money(row[4]),
        unknown_units=int(row[5]),
        unknown_revenue=int(row[6]),
        unknown_lines=int(row[7]),
    )


async def _line_loss_amount(db: AsyncSession, scope: ReportScope) -> Decimal:
    """Sum of absolute negative margins across realized known-cost lines."""
    dialect = dialect_name(db)
    num = _sql_num(dialect)
    order_merch = (
        select(
            OrderItem.order_id.label("order_id"),
            func.sum(OrderItem.line_total).label("merch"),
        )
        .group_by(OrderItem.order_id)
        .subquery()
    )
    discount = func.coalesce(Order.coupon_discount, 0) + func.coalesce(Order.manual_discount, 0)
    share = case(
        (
            order_merch.c.merch > 0,
            _coupon_ratio(discount, OrderItem.line_total, order_merch.c.merch, dialect),
        ),
        else_=0,
    )
    line_net = cast(OrderItem.line_total - share, num)
    line_cost = cast(OrderItem.quantity * OrderItem.unit_cost, num)
    line_diff = line_net - line_cost
    stmt = (
        select(func.coalesce(func.sum(case((line_diff < 0, -line_diff), else_=0)), 0))
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(order_merch, order_merch.c.order_id == Order.id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .where(
            at_or_after(Order.delivered_at, scope.start, dialect),
            before(Order.delivered_at, scope.end, dialect),
            _realized_order_cond(),
            OrderItem.unit_cost.is_not(None),
        )
    )
    if scope.channel is not None:
        stmt = stmt.where(Order.channel == scope.channel)
    if scope.origin is not None:
        stmt = stmt.where(Order.origin == scope.origin)
    if scope.product_id is not None:
        stmt = stmt.where(OrderItem.product_id == scope.product_id)
    if scope.category_ids is not None:
        stmt = stmt.where(Product.category_id.in_(scope.category_ids))
    if scope.supplier_id is not None:
        stmt = stmt.where(Product.supplier_id == scope.supplier_id)
    raw = await db.scalar(stmt)
    return _money(raw) or Decimal("0.00")


def _profit_of(totals: _LineTotals) -> tuple[Decimal | None, Decimal | None]:
    if totals.cost is None:
        return None, None
    profit = (Decimal(totals.known_revenue) - totals.cost).quantize(
        _TWOPLACES, rounding=ROUND_HALF_UP
    )
    if totals.known_revenue == 0:
        return profit, None
    margin = (profit * Decimal(100) / Decimal(totals.known_revenue)).quantize(
        _TWOPLACES, rounding=ROUND_HALF_UP
    )
    return profit, margin


def _whole(value: object) -> int:
    if value is None:
        return 0
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _coupon_ratio(discount: Any, part: Any, merch: Any, dialect: str) -> Any:
    """Whole taka, half up for positive amounts. SQLite divides in float."""
    number = Numeric if dialect == "postgresql" else Float
    return func.round(cast(discount, number) * cast(part, number) / cast(merch, number))


def _coupon_share_query(scope: ReportScope, dialect: str) -> Any:
    """One row per delivered order: its coupon & manual discount split across matching lines."""
    line_match: list[Any] = []
    if scope.product_id is not None:
        line_match.append(OrderItem.product_id == scope.product_id)
    if scope.category_ids is not None:
        line_match.append(Product.category_id.in_(scope.category_ids))
    if scope.supplier_id is not None:
        line_match.append(Product.supplier_id == scope.supplier_id)
    matched_expr = and_(*line_match) if line_match else true()
    known = OrderItem.unit_cost.is_not(None)
    unknown = OrderItem.unit_cost.is_(None)
    parts = (
        select(
            OrderItem.order_id.label("order_id"),
            func.sum(OrderItem.line_total).label("merch"),
            func.sum(case((matched_expr, OrderItem.line_total), else_=0)).label("matched_lines"),
            func.sum(case((and_(matched_expr, known), OrderItem.line_total), else_=0)).label(
                "known_lines"
            ),
            func.sum(case((and_(matched_expr, unknown), OrderItem.line_total), else_=0)).label(
                "unknown_lines"
            ),
        )
        .select_from(OrderItem)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .group_by(OrderItem.order_id)
        .subquery()
    )
    coupon_only = func.coalesce(Order.coupon_discount, 0)
    # manual_discount is the staff order-level discount. 0 on every older row.
    manual_only = func.coalesce(Order.manual_discount, 0)
    discount = coupon_only + manual_only
    stmt = (
        select(
            Order.id.label("order_id"),
            Order.origin.label("origin"),
            Order.payment_method.label("payment_method"),
            dhaka_day(Order.delivered_at, dialect).label("day"),
            _coupon_ratio(discount, parts.c.matched_lines, parts.c.merch, dialect).label("matched"),
            _coupon_ratio(discount, parts.c.known_lines, parts.c.merch, dialect).label("known"),
            _coupon_ratio(discount, parts.c.unknown_lines, parts.c.merch, dialect).label("unknown"),
            _coupon_ratio(coupon_only, parts.c.matched_lines, parts.c.merch, dialect).label(
                "coupon_only"
            ),
            _coupon_ratio(manual_only, parts.c.matched_lines, parts.c.merch, dialect).label(
                "manual_only"
            ),
        )
        .select_from(Order)
        .join(parts, parts.c.order_id == Order.id)
        .where(
            at_or_after(Order.delivered_at, scope.start, dialect),
            before(Order.delivered_at, scope.end, dialect),
            _realized_order_cond(),
            parts.c.merch > 0,
            parts.c.matched_lines > 0,
        )
    )
    if scope.channel is not None:
        stmt = stmt.where(Order.channel == scope.channel)
    if scope.origin is not None:
        stmt = stmt.where(Order.origin == scope.origin)
    return stmt.subquery()


async def _coupon_shares(db: AsyncSession, scope: ReportScope) -> _CouponShares:
    shares = _coupon_share_query(scope, dialect_name(db))
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(shares.c.matched), 0),
                func.coalesce(func.sum(shares.c.known), 0),
                func.coalesce(func.sum(shares.c.unknown), 0),
                func.coalesce(func.sum(shares.c.coupon_only), 0),
                func.coalesce(func.sum(shares.c.manual_only), 0),
            )
        )
    ).one()
    return _CouponShares(
        matched=_whole(row[0]),
        known=_whole(row[1]),
        unknown=_whole(row[2]),
        coupon_only=_whole(row[3]),
        manual_only=_whole(row[4]),
    )


async def sales_summary(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> SalesSummary:
    scope = await _scope(db, request, now)
    orders, shipping = await _order_shipping(db, scope)
    totals = await _line_totals(db, scope)
    coupon = await _coupon_shares(db, scope)
    discount = totals.gross - totals.merchandise + coupon.matched
    return SalesSummary(
        filters=scope.filters(),
        order_count=orders,
        units_sold=totals.units,
        gross_sales=totals.gross,
        discount=discount,
        coupon_discount=coupon.coupon_only,
        manual_discount=coupon.manual_only,
        delivery_charge=shipping,
        net_sales=totals.merchandise + shipping - coupon.matched,
    )


async def profit_report(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> ProfitReport:
    scope = await _scope(db, request, now)
    totals = await _line_totals(db, scope)
    coupon = await _coupon_shares(db, scope)
    loss_amount = await _line_loss_amount(db, scope)
    totals.known_revenue = max(totals.known_revenue - coupon.known, 0)
    totals.unknown_revenue = max(totals.unknown_revenue - coupon.unknown, 0)
    profit, margin = _profit_of(totals)
    return ProfitReport(
        filters=scope.filters(),
        revenue=totals.known_revenue,
        cost=totals.cost,
        profit=profit,
        loss_amount=loss_amount,
        net_profit=profit,
        margin_percent=margin,
        unknown_cost_lines=totals.unknown_lines,
        unknown_cost_units=totals.unknown_units,
        unknown_cost_revenue=totals.unknown_revenue,
    )


async def profit_loss_report(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> ProfitLossReport:
    scope = await _scope(db, request, now)
    _orders, shipping = await _order_shipping(db, scope)
    totals = await _line_totals(db, scope)
    coupon = await _coupon_shares(db, scope)
    returned_value = await _returned_value(db, scope)
    collected, due = await _order_collections(db, scope)
    loss_amount = await _line_loss_amount(db, scope)

    product_discount = totals.gross - totals.merchandise
    net_realized_sales = totals.merchandise + shipping - coupon.matched
    totals.known_revenue = max(totals.known_revenue - coupon.known, 0)
    totals.unknown_revenue = max(totals.unknown_revenue - coupon.unknown, 0)

    if totals.cost is not None:
        total_cost: Decimal | None = totals.cost
        gross_profit, margin = _profit_of(totals)
        net_profit = gross_profit
    elif totals.unknown_lines > 0:
        total_cost = None
        gross_profit = None
        net_profit = None
        margin = None
    else:
        total_cost = Decimal("0.00")
        gross_profit = Decimal("0.00")
        net_profit = Decimal("0.00")
        margin = None

    return ProfitLossReport(
        filters=scope.filters(),
        gross_sales=totals.gross,
        product_discount=product_discount,
        coupon_discount=coupon.coupon_only,
        manual_discount=coupon.manual_only,
        delivery_charge=shipping,
        returned_order_value=returned_value,
        net_realized_sales=net_realized_sales,
        total_cost=total_cost,
        gross_profit=gross_profit,
        loss_amount=loss_amount,
        net_profit=net_profit,
        margin_percent=margin,
        collected_amount=collected,
        due_amount=due,
        unknown_cost_lines=totals.unknown_lines,
        unknown_cost_units=totals.unknown_units,
        unknown_cost_revenue=totals.unknown_revenue,
    )


def _product_groups(scope: ReportScope, dialect: str) -> Any:
    delivered = and_(
        at_or_after(Order.delivered_at, scope.start, dialect),
        before(Order.delivered_at, scope.end, dialect),
        _realized_order_cond(),
    )
    returned = and_(
        at_or_after(Order.returned_at, scope.start, dialect),
        before(Order.returned_at, scope.end, dialect),
    )
    known = OrderItem.unit_cost.is_not(None)
    group_key = func.coalesce(cast(OrderItem.product_id, String), OrderItem.title)
    order_merch = (
        select(
            OrderItem.order_id.label("order_id"),
            func.sum(OrderItem.line_total).label("merch"),
        )
        .group_by(OrderItem.order_id)
        .subquery()
    )
    variant_sku = (
        select(
            ProductVariant.product_id.label("product_id"),
            func.min(case((ProductVariant.sku != "", ProductVariant.sku))).label("sku"),
        )
        .group_by(ProductVariant.product_id)
        .subquery()
    )
    discount = func.coalesce(Order.coupon_discount, 0) + func.coalesce(Order.manual_discount, 0)
    share = case(
        (
            and_(delivered, order_merch.c.merch > 0),
            _coupon_ratio(discount, OrderItem.line_total, order_merch.c.merch, dialect),
        ),
        else_=0,
    )
    known_share = case((and_(delivered, known), share), else_=0)
    stock_val_expr = case(
        (
            and_(Product.quantity.is_not(None), Product.cost_price.is_not(None)),
            Product.quantity * Product.cost_price,
        )
    )
    stmt = (
        select(
            func.max(cast(OrderItem.product_id, String)).label("product_id"),
            func.max(func.coalesce(Product.title, OrderItem.title)).label("title"),
            func.max(func.coalesce(Product.slug, OrderItem.slug, "")).label("slug"),
            func.coalesce(
                func.max(case((OrderItem.sku != "", OrderItem.sku))),
                func.max(variant_sku.c.sku),
                "",
            ).label("sku"),
            func.coalesce(func.max(Category.name), "").label("category_name"),
            func.max(cast(Product.supplier_id, String)).label("supplier_id"),
            func.max(Supplier.name).label("supplier_name"),
            func.max(Product.cost_price).label("current_cost_price"),
            func.max(Product.quantity).label("current_stock"),
            func.max(stock_val_expr).label("stock_value"),
            func.coalesce(func.sum(case((delivered, OrderItem.quantity), else_=0)), 0).label(
                "units_sold"
            ),
            func.coalesce(
                func.sum(case((and_(delivered, known), OrderItem.quantity), else_=0)), 0
            ).label("known_units"),
            (
                func.coalesce(func.sum(case((delivered, OrderItem.line_total), else_=0)), 0)
                - func.coalesce(func.sum(share), 0)
            ).label("revenue"),
            (
                func.sum(case((and_(delivered, known), OrderItem.line_total)))
                - func.coalesce(func.sum(known_share), 0)
            ).label("known_revenue"),
            func.sum(
                case((and_(delivered, known), OrderItem.quantity * OrderItem.unit_cost))
            ).label("cost"),
            func.coalesce(
                func.sum(
                    case(
                        (and_(delivered, OrderItem.unit_cost.is_(None)), OrderItem.quantity),
                        else_=0,
                    )
                ),
                0,
            ).label("unknown_units"),
            func.count(distinct(case((returned, Order.id)))).label("return_count"),
            func.coalesce(func.sum(case((returned, OrderItem.quantity), else_=0)), 0).label(
                "returned_units"
            ),
            func.coalesce(func.sum(case((returned, OrderItem.line_total), else_=0)), 0).label(
                "return_value"
            ),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(order_merch, order_merch.c.order_id == Order.id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .outerjoin(Category, Category.id == Product.category_id)
        .outerjoin(Supplier, Supplier.id == Product.supplier_id)
        .outerjoin(variant_sku, variant_sku.c.product_id == Product.id)
        .where(or_(delivered, returned))
        .group_by(group_key)
    )
    if scope.channel is not None:
        stmt = stmt.where(Order.channel == scope.channel)
    if scope.origin is not None:
        stmt = stmt.where(Order.origin == scope.origin)
    if scope.product_id is not None:
        stmt = stmt.where(OrderItem.product_id == scope.product_id)
    if scope.category_ids is not None:
        stmt = stmt.where(Product.category_id.in_(scope.category_ids))
    if scope.supplier_id is not None:
        stmt = stmt.where(Product.supplier_id == scope.supplier_id)
    return stmt


def _product_row(row: Any) -> ProductReportRow:
    known_revenue = row.known_revenue
    cost = _money(row.cost)
    revenue = _whole(row.revenue)
    units_sold = int(row.units_sold)
    known_units = int(row.known_units)
    avg_selling_price: Decimal | None = None
    if units_sold > 0:
        avg_selling_price = (Decimal(revenue) / Decimal(units_sold)).quantize(
            _TWOPLACES, rounding=ROUND_HALF_UP
        )
    unit_cost_avg: Decimal | None = None
    if cost is not None and known_units > 0:
        unit_cost_avg = (cost / Decimal(known_units)).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)

    if cost is None:
        profit, margin = None, None
    else:
        known = 0 if known_revenue is None else _whole(known_revenue)
        profit = (Decimal(known) - cost).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
        margin = (
            None
            if known == 0
            else (profit * Decimal(100) / Decimal(known)).quantize(
                _TWOPLACES, rounding=ROUND_HALF_UP
            )
        )
    return ProductReportRow(
        product_id=_uuid(row.product_id),
        title=str(row.title or "Removed product"),
        slug=str(row.slug or ""),
        sku=str(row.sku or ""),
        category_name=str(row.category_name or ""),
        supplier_id=_uuid(row.supplier_id),
        supplier_name=str(row.supplier_name) if row.supplier_name is not None else None,
        units_sold=units_sold,
        avg_selling_price=avg_selling_price,
        unit_cost_avg=unit_cost_avg,
        current_cost_price=_money(row.current_cost_price),
        current_stock=int(row.current_stock) if row.current_stock is not None else None,
        stock_value=_money(row.stock_value),
        revenue=revenue,
        cost=cost,
        profit=profit,
        is_loss=bool(profit is not None and profit < 0),
        margin_percent=margin,
        return_count=int(row.return_count),
        returned_units=int(row.returned_units),
        return_value=int(row.return_value),
        unknown_cost_units=int(row.unknown_units),
    )


async def _product_page(
    db: AsyncSession,
    scope: ReportScope,
    *,
    offset: int,
    limit: int,
    sort: ProductReportSort = "revenue",
) -> tuple[list[ProductReportRow], int]:
    dialect = dialect_name(db)
    num = _sql_num(dialect)
    grouped = _product_groups(scope, dialect).subquery()

    profit_expr = case(
        (
            grouped.c.cost.is_not(None),
            cast(func.coalesce(grouped.c.known_revenue, 0), num) - cast(grouped.c.cost, num),
        )
    )
    margin_expr = case(
        (
            and_(grouped.c.cost.is_not(None), func.coalesce(grouped.c.known_revenue, 0) > 0),
            (cast(grouped.c.known_revenue, num) - cast(grouped.c.cost, num))
            * 100.0
            / cast(grouped.c.known_revenue, num),
        )
    )

    conds: list[Any] = []
    if scope.profit_filter == "profit":
        conds.append(and_(grouped.c.cost.is_not(None), profit_expr > 0))
    elif scope.profit_filter == "loss":
        conds.append(and_(grouped.c.cost.is_not(None), profit_expr < 0))
    elif scope.profit_filter == "unknown_cost":
        conds.append(grouped.c.unknown_units > 0)

    count_stmt = select(func.count()).select_from(grouped)
    if conds:
        count_stmt = count_stmt.where(*conds)
    total = int((await db.scalar(count_stmt)) or 0)

    order_map: dict[ProductReportSort, list[Any]] = {
        "revenue": [grouped.c.revenue.desc(), grouped.c.units_sold.desc(), grouped.c.title.asc()],
        "profit": [
            profit_expr.desc().nulls_last(),
            grouped.c.revenue.desc(),
            grouped.c.title.asc(),
        ],
        "margin": [
            margin_expr.desc().nulls_last(),
            profit_expr.desc().nulls_last(),
            grouped.c.title.asc(),
        ],
        "units_sold": [
            grouped.c.units_sold.desc(),
            grouped.c.revenue.desc(),
            grouped.c.title.asc(),
        ],
        "cost": [
            grouped.c.cost.desc().nulls_last(),
            grouped.c.revenue.desc(),
            grouped.c.title.asc(),
        ],
        "stock_value": [
            grouped.c.stock_value.desc().nulls_last(),
            grouped.c.revenue.desc(),
            grouped.c.title.asc(),
        ],
    }

    listed = select(grouped)
    if conds:
        listed = listed.where(*conds)
    rows = (await db.execute(listed.order_by(*order_map[sort]).offset(offset).limit(limit))).all()
    return [_product_row(row) for row in rows], total


async def product_report(
    db: AsyncSession,
    request: ReportRequest,
    *,
    page: int,
    page_size: int,
    now: datetime | None = None,
) -> ProductReport:
    scope = await _scope(db, request, now)
    sort = _parse_product_sort(request.sort)
    items, total = await _product_page(
        db, scope, offset=(page - 1) * page_size, limit=page_size, sort=sort
    )
    return ProductReport(
        filters=scope.filters(),
        sort=sort,
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


async def _group_breakdown(
    db: AsyncSession, scope: ReportScope, group_col: Any, share_col_name: str
) -> dict[str, _GroupTotals]:
    dialect = dialect_name(db)
    known = OrderItem.unit_cost.is_not(None)
    unknown = OrderItem.unit_cost.is_(None)
    buckets: dict[str, _GroupTotals] = {}

    order_rows = (
        await db.execute(
            select(
                group_col,
                func.count(),
                func.coalesce(func.sum(Order.shipping), 0),
                func.coalesce(func.sum(_effective_collected_expr()), 0),
                func.coalesce(func.sum(_effective_due_expr()), 0),
            )
            .select_from(Order)
            .where(*_order_filters(scope, Order.delivered_at, dialect, _realized_order_cond()))
            .group_by(group_col)
        )
    ).all()
    for key, count, shipping, collected, due in order_rows:
        bucket = buckets.setdefault(str(key), _GroupTotals())
        bucket.order_count = int(count)
        bucket.shipping = int(shipping)
        bucket.collected = int(collected)
        bucket.due = int(due)

    line_rows = (
        await db.execute(
            _line_statement(
                scope,
                [
                    group_col,
                    func.coalesce(func.sum(OrderItem.quantity), 0),
                    func.coalesce(func.sum(OrderItem.line_total), 0),
                    func.coalesce(func.sum(case((known, OrderItem.line_total), else_=0)), 0),
                    func.sum(case((known, OrderItem.quantity * OrderItem.unit_cost))),
                    func.coalesce(func.sum(case((unknown, OrderItem.quantity), else_=0)), 0),
                ],
                dialect,
            ).group_by(group_col)
        )
    ).all()
    for key, units, merch, known_merch, cost, unknown_units in line_rows:
        bucket = buckets.setdefault(str(key), _GroupTotals())
        bucket.units = int(units)
        bucket.merchandise = int(merch)
        bucket.known_merchandise = int(known_merch)
        bucket.cost = _money(cost)
        bucket.unknown_units = int(unknown_units)

    shares = _coupon_share_query(scope, dialect)
    share_key = getattr(shares.c, share_col_name)
    share_rows = (
        await db.execute(
            select(
                share_key,
                func.coalesce(func.sum(shares.c.matched), 0),
                func.coalesce(func.sum(shares.c.known), 0),
            ).group_by(share_key)
        )
    ).all()
    for key, matched, known_disc in share_rows:
        bucket = buckets.setdefault(str(key), _GroupTotals())
        bucket.matched_discount = _whole(matched)
        bucket.known_discount = _whole(known_disc)

    return buckets


def _group_profit_metrics(
    bucket: _GroupTotals,
) -> tuple[int, Decimal | None, Decimal | None, Decimal | None]:
    net_sales = bucket.merchandise + bucket.shipping - bucket.matched_discount
    known_rev = max(bucket.known_merchandise - bucket.known_discount, 0)
    if bucket.cost is not None:
        cogs: Decimal | None = bucket.cost
        net_val = (Decimal(known_rev) - bucket.cost).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
        profit: Decimal | None = net_val
        margin: Decimal | None = (
            (net_val * Decimal(100) / Decimal(known_rev)).quantize(
                _TWOPLACES, rounding=ROUND_HALF_UP
            )
            if known_rev > 0
            else None
        )
    elif bucket.unknown_units > 0:
        cogs, profit, margin = None, None, None
    else:
        cogs = Decimal("0.00")
        profit = Decimal("0.00")
        margin = None
    return net_sales, cogs, profit, margin


async def channel_report(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> ChannelBreakdownReport:
    scope = await _scope(db, request, now)
    by_origin = await _group_breakdown(db, scope, Order.origin, "origin")
    by_payment = await _group_breakdown(db, scope, Order.payment_method, "payment_method")

    channels: list[ChannelBreakdownRow] = []
    for origin in ORIGINS:
        bucket = by_origin.get(origin, _GroupTotals())
        net_sales, cogs, profit, margin = _group_profit_metrics(bucket)
        channels.append(
            ChannelBreakdownRow(
                origin=origin,
                channel="website" if origin == OrderOrigin.ONLINE.value else "offline",
                order_count=bucket.order_count,
                units=bucket.units,
                net_sales=net_sales,
                cogs=cogs,
                profit=profit,
                margin_percent=margin,
                collected=bucket.collected,
                due=bucket.due,
                unknown_cost_units=bucket.unknown_units,
            )
        )

    ordered_methods = list(CANONICAL_PAYMENT_METHODS)
    for extra in sorted(by_payment):
        if extra not in ordered_methods:
            ordered_methods.append(extra)
    payment_methods: list[PaymentMethodBreakdownRow] = []
    for method in ordered_methods:
        bucket = by_payment.get(method, _GroupTotals())
        net_sales, cogs, profit, margin = _group_profit_metrics(bucket)
        payment_methods.append(
            PaymentMethodBreakdownRow(
                payment_method=method,
                order_count=bucket.order_count,
                units=bucket.units,
                net_sales=net_sales,
                cogs=cogs,
                profit=profit,
                margin_percent=margin,
                collected=bucket.collected,
                due=bucket.due,
                unknown_cost_units=bucket.unknown_units,
            )
        )

    return ChannelBreakdownReport(
        filters=scope.filters(),
        channels=channels,
        payment_methods=payment_methods,
    )


async def supplier_report(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> SupplierPerformanceReport:
    scope = await _scope(db, request, now)
    dialect = dialect_name(db)

    supplier_stmt = select(Supplier.id, Supplier.name)
    if scope.supplier_id is not None:
        supplier_stmt = supplier_stmt.where(Supplier.id == scope.supplier_id)
    else:
        supplier_stmt = supplier_stmt.where(Supplier.is_deleted.is_(False))
    supplier_rows = (await db.execute(supplier_stmt.order_by(Supplier.name.asc()))).all()
    supplier_names: dict[uuid.UUID, str] = {row[0]: str(row[1]) for row in supplier_rows}

    # 1. Linked products & current stock value per supplier
    stock_filters = [Product.supplier_id.is_not(None), *_stock_filters(scope)]
    valued = and_(Product.quantity.is_not(None), Product.cost_price.is_not(None))
    stock_rows = (
        await db.execute(
            select(
                Product.supplier_id,
                func.count(Product.id),
                func.coalesce(func.sum(Product.quantity), 0),
                func.coalesce(
                    func.sum(case((valued, Product.quantity * Product.cost_price), else_=0)), 0
                ),
            )
            .select_from(Product)
            .where(*stock_filters)
            .group_by(Product.supplier_id)
        )
    ).all()
    stock_map: dict[uuid.UUID, tuple[int, int, Decimal]] = {
        row[0]: (int(row[1]), int(row[2]), _money(row[3]) or Decimal("0.00"))
        for row in stock_rows
        if row[0] is not None
    }

    # 2. Purchases in window per supplier (purchased_on is a Dhaka calendar date)
    purchase_stmt = (
        select(
            Purchase.supplier_id,
            func.count(distinct(Purchase.id)),
            func.coalesce(func.sum(PurchaseItem.quantity), 0),
            func.coalesce(func.sum(PurchaseItem.quantity * PurchaseItem.unit_cost), 0),
        )
        .select_from(Purchase)
        .join(PurchaseItem, PurchaseItem.purchase_id == Purchase.id)
        .outerjoin(Product, Product.id == PurchaseItem.product_id)
        .where(
            Purchase.purchased_on >= scope.date_from,
            Purchase.purchased_on <= scope.date_to,
        )
        .group_by(Purchase.supplier_id)
    )
    if scope.supplier_id is not None:
        purchase_stmt = purchase_stmt.where(Purchase.supplier_id == scope.supplier_id)
    if scope.product_id is not None:
        purchase_stmt = purchase_stmt.where(PurchaseItem.product_id == scope.product_id)
    if scope.category_ids is not None:
        purchase_stmt = purchase_stmt.where(Product.category_id.in_(scope.category_ids))
    purchase_rows = (await db.execute(purchase_stmt)).all()
    purchase_map: dict[uuid.UUID, tuple[int, int, Decimal]] = {
        row[0]: (int(row[1]), int(row[2]), _money(row[3]) or Decimal("0.00"))
        for row in purchase_rows
        if row[0] is not None
    }

    # 3. Realized sales & profit in window per product's supplier
    order_merch = (
        select(
            OrderItem.order_id.label("order_id"),
            func.sum(OrderItem.line_total).label("merch"),
        )
        .group_by(OrderItem.order_id)
        .subquery()
    )
    known = OrderItem.unit_cost.is_not(None)
    unknown = OrderItem.unit_cost.is_(None)
    discount = func.coalesce(Order.coupon_discount, 0) + func.coalesce(Order.manual_discount, 0)
    share = case(
        (
            order_merch.c.merch > 0,
            _coupon_ratio(discount, OrderItem.line_total, order_merch.c.merch, dialect),
        ),
        else_=0,
    )
    known_share = case((known, share), else_=0)
    sales_stmt = (
        select(
            Product.supplier_id,
            func.coalesce(func.sum(OrderItem.quantity), 0),
            func.coalesce(func.sum(OrderItem.line_total), 0) - func.coalesce(func.sum(share), 0),
            func.sum(case((known, OrderItem.line_total))) - func.coalesce(func.sum(known_share), 0),
            func.sum(case((known, OrderItem.quantity * OrderItem.unit_cost))),
            func.coalesce(func.sum(case((unknown, OrderItem.quantity), else_=0)), 0),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .outerjoin(order_merch, order_merch.c.order_id == Order.id)
        .where(
            Product.supplier_id.is_not(None),
            at_or_after(Order.delivered_at, scope.start, dialect),
            before(Order.delivered_at, scope.end, dialect),
            _realized_order_cond(),
        )
        .group_by(Product.supplier_id)
    )
    if scope.channel is not None:
        sales_stmt = sales_stmt.where(Order.channel == scope.channel)
    if scope.origin is not None:
        sales_stmt = sales_stmt.where(Order.origin == scope.origin)
    if scope.product_id is not None:
        sales_stmt = sales_stmt.where(OrderItem.product_id == scope.product_id)
    if scope.category_ids is not None:
        sales_stmt = sales_stmt.where(Product.category_id.in_(scope.category_ids))
    if scope.supplier_id is not None:
        sales_stmt = sales_stmt.where(Product.supplier_id == scope.supplier_id)
    sales_rows = (await db.execute(sales_stmt)).all()
    sales_map: dict[uuid.UUID, tuple[int, int, int | None, Decimal | None, int]] = {
        row[0]: (
            int(row[1]),
            _whole(row[2]),
            None if row[3] is None else _whole(row[3]),
            _money(row[4]),
            int(row[5]),
        )
        for row in sales_rows
        if row[0] is not None
    }

    # Include any soft-deleted suppliers that had purchases/sales in this window.
    extra_ids = (set(stock_map) | set(purchase_map) | set(sales_map)) - set(supplier_names)
    if extra_ids:
        extra_rows = (
            await db.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(extra_ids)))
        ).all()
        for sid, sname in extra_rows:
            supplier_names[sid] = str(sname)

    items: list[SupplierPerformanceRow] = []
    total_spend = Decimal("0.00")
    total_revenue = 0
    total_cogs_acc = Decimal("0.00")
    total_profit_acc = Decimal("0.00")
    any_known_sales = False
    any_unknown_sales = False

    for sid, sname in supplier_names.items():
        linked_products, stock_units, stock_value = stock_map.get(sid, (0, 0, Decimal("0.00")))
        p_count, p_units, p_spend = purchase_map.get(sid, (0, 0, Decimal("0.00")))
        s_units, s_rev, s_known_rev, s_cogs, s_unknown = sales_map.get(sid, (0, 0, None, None, 0))

        if s_cogs is not None:
            known_rev_val = max(s_known_rev or 0, 0)
            row_cogs: Decimal | None = s_cogs
            net_val = (Decimal(known_rev_val) - s_cogs).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
            row_profit: Decimal | None = net_val
            row_margin: Decimal | None = (
                (net_val * Decimal(100) / Decimal(known_rev_val)).quantize(
                    _TWOPLACES, rounding=ROUND_HALF_UP
                )
                if known_rev_val > 0
                else None
            )
            any_known_sales = True
            total_cogs_acc += s_cogs
            total_profit_acc += net_val
        elif s_unknown > 0:
            row_cogs = None
            row_profit = None
            row_margin = None
            any_unknown_sales = True
        else:
            row_cogs = Decimal("0.00")
            row_profit = Decimal("0.00")
            row_margin = None

        total_spend += p_spend
        total_revenue += s_rev

        items.append(
            SupplierPerformanceRow(
                supplier_id=sid,
                supplier_name=sname,
                linked_products_count=linked_products,
                purchase_count=p_count,
                total_purchased_units=p_units,
                total_purchase_spend=p_spend,
                units_sold=s_units,
                sales_revenue=s_rev,
                cogs=row_cogs,
                net_profit=row_profit,
                margin_percent=row_margin,
                current_stock_units=stock_units,
                current_stock_value=stock_value,
                unknown_cost_units=s_unknown,
            )
        )

    items.sort(key=lambda r: (-r.sales_revenue, -r.total_purchase_spend, r.supplier_name.lower()))

    if any_known_sales:
        report_cogs: Decimal | None = total_cogs_acc.quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
        report_profit: Decimal | None = total_profit_acc.quantize(
            _TWOPLACES, rounding=ROUND_HALF_UP
        )
    elif any_unknown_sales:
        report_cogs = None
        report_profit = None
    else:
        report_cogs = Decimal("0.00")
        report_profit = Decimal("0.00")

    return SupplierPerformanceReport(
        filters=scope.filters(),
        items=items,
        total_purchase_spend=total_spend.quantize(_TWOPLACES, rounding=ROUND_HALF_UP),
        total_sales_revenue=total_revenue,
        total_cogs=report_cogs,
        total_net_profit=report_profit,
    )


def _no_sale(start: datetime, end: datetime, dialect: str) -> Any:
    return ~(
        select(OrderItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            OrderItem.product_id == Product.id,
            at_or_after(Order.delivered_at, start, dialect),
            before(Order.delivered_at, end, dialect),
            _realized_order_cond(),
        )
        .exists()
    )


def _stock_filters(scope: ReportScope) -> list[Any]:
    conds: list[Any] = []
    if scope.product_id is not None:
        conds.append(Product.id == scope.product_id)
    if scope.category_ids is not None:
        conds.append(Product.category_id.in_(scope.category_ids))
    if scope.supplier_id is not None:
        conds.append(Product.supplier_id == scope.supplier_id)
    return conds


async def stock_report(
    db: AsyncSession,
    request: ReportRequest,
    *,
    page: int,
    page_size: int,
    now: datetime | None = None,
) -> StockReport:
    scope = await _scope(db, request, now)
    moment = (now or datetime.now(SHOP)).astimezone(SHOP)
    as_of = moment.date()
    no_sale_since = as_of - timedelta(days=29)
    sale_start = datetime(no_sale_since.year, no_sale_since.month, no_sale_since.day, tzinfo=SHOP)
    sale_end = datetime(as_of.year, as_of.month, as_of.day, tzinfo=SHOP) + timedelta(days=1)
    items, total, summary = await _stock_page(
        db,
        scope,
        sale_start=sale_start,
        sale_end=sale_end,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return StockReport(
        filters=scope.filters(channel_applies=False),
        as_of=as_of,
        no_sale_since=no_sale_since,
        summary=summary,
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


async def _stock_page(
    db: AsyncSession,
    scope: ReportScope,
    *,
    sale_start: datetime,
    sale_end: datetime,
    offset: int,
    limit: int,
) -> tuple[list[StockRow], int, StockSummary]:
    no_sale = _no_sale(sale_start, sale_end, dialect_name(db))
    tracked = Product.quantity.is_not(None)
    valued = and_(tracked, Product.cost_price.is_not(None))
    low = and_(tracked, Product.quantity <= LOW_STOCK_AT)
    filters = _stock_filters(scope)
    summary_row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Product.quantity), 0),
                func.coalesce(
                    func.sum(case((valued, Product.quantity * Product.cost_price))),
                    0,
                ),
                func.coalesce(
                    func.sum(case((tracked, Product.quantity * Product.price))),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case((valued, Product.quantity * (Product.price - Product.cost_price)))
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(case((Product.cost_price.is_(None), 1), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (and_(tracked, Product.cost_price.is_(None)), Product.quantity),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(func.sum(case((low, 1), else_=0)), 0),
                func.coalesce(func.sum(case((no_sale, 1), else_=0)), 0),
            )
            .select_from(Product)
            .where(*filters)
        )
    ).one()
    value_col = case((valued, Product.quantity * Product.cost_price)).label("stock_value")
    retail_col = case((tracked, Product.quantity * Product.price)).label("potential_retail_value")
    expected_profit_col = case(
        (valued, Product.quantity * (Product.price - Product.cost_price))
    ).label("expected_profit_on_hand")
    low_col = case((low, 1), else_=0).label("low_stock")
    idle_col = case((no_sale, 1), else_=0).label("no_sale_30d")
    listed = (
        select(
            Product.id,
            Product.title,
            Product.quantity,
            Product.price,
            Product.cost_price,
            value_col,
            retail_col,
            expected_profit_col,
            Supplier.name.label("supplier_name"),
            low_col,
            idle_col,
        )
        .select_from(Product)
        .outerjoin(Supplier, Supplier.id == Product.supplier_id)
        .where(*filters)
        .order_by(low_col.desc(), Product.quantity.asc().nulls_last(), Product.title.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(listed)).all()
    items = [
        StockRow(
            product_id=row.id,
            title=row.title,
            quantity=row.quantity,
            selling_price=int(row.price),
            cost_price=_money(row.cost_price),
            stock_value=_money(row.stock_value),
            potential_retail_value=_money(row.potential_retail_value),
            expected_profit_on_hand=_money(row.expected_profit_on_hand),
            supplier_name=str(row.supplier_name) if row.supplier_name is not None else None,
            low_stock=bool(row.low_stock),
            no_sale_30d=bool(row.no_sale_30d),
        )
        for row in rows
    ]
    summary = StockSummary(
        product_count=int(summary_row[0]),
        units_on_hand=int(summary_row[1]),
        stock_value=_money(summary_row[2]) or Decimal("0.00"),
        potential_retail_value=_money(summary_row[3]) or Decimal("0.00"),
        expected_profit_on_hand=_money(summary_row[4]) or Decimal("0.00"),
        missing_cost_count=int(summary_row[5]),
        unknown_cost_units=int(summary_row[6]),
        low_stock_count=int(summary_row[7]),
        low_stock_at=LOW_STOCK_AT,
        no_sale_30d_count=int(summary_row[8]),
    )
    return items, summary.product_count, summary


async def movement_report(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> MovementReport:
    scope = await _scope(db, request, now)
    dialect = dialect_name(db)
    in_period = and_(
        at_or_after(StockMovement.created_at, scope.start, dialect),
        before(StockMovement.created_at, scope.end, dialect),
    )
    before_end = before(StockMovement.created_at, scope.end, dialect)
    before_start = before(StockMovement.created_at, scope.start, dialect)

    def typed(name: str) -> Any:
        return func.coalesce(
            func.sum(
                case(
                    (and_(in_period, StockMovement.movement_type == name), StockMovement.quantity),
                    else_=0,
                )
            ),
            0,
        )

    stmt = select(
        func.coalesce(func.sum(case((before_start, StockMovement.quantity), else_=0)), 0),
        typed("opening"),
        typed("purchase"),
        typed("sale"),
        typed("return"),
        typed("cancel"),
        typed("adjustment"),
        func.coalesce(func.sum(case((before_end, StockMovement.quantity), else_=0)), 0),
    ).select_from(StockMovement)
    if scope.category_ids is not None or scope.supplier_id is not None:
        stmt = stmt.join(Product, Product.id == StockMovement.product_id)
    stmt = stmt.where(before_end)
    if scope.product_id is not None:
        stmt = stmt.where(StockMovement.product_id == scope.product_id)
    if scope.category_ids is not None:
        stmt = stmt.where(Product.category_id.in_(scope.category_ids))
    if scope.supplier_id is not None:
        stmt = stmt.where(Product.supplier_id == scope.supplier_id)
    row = (await db.execute(stmt)).one()
    return MovementReport(
        filters=scope.filters(channel_applies=False),
        opening_balance=int(row[0]),
        opening=int(row[1]),
        purchase=int(row[2]),
        sale=int(row[3]),
        return_total=int(row[4]),
        cancel=int(row[5]),
        adjustment=int(row[6]),
        closing=int(row[7]),
    )


async def delivery_report(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> DeliveryReport:
    scope = await _scope(db, request, now)
    dialect = dialect_name(db)
    delivered = await _count(db, _order_filters(scope, Order.delivered_at, dialect))
    returned_conds = _order_filters(scope, Order.returned_at, dialect)
    returned_row = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.total), 0))
            .select_from(Order)
            .where(*returned_conds)
        )
    ).one()
    returned = int(returned_row[0])
    returned_value = int(returned_row[1])
    cancelled = await _count(
        db, _order_filters(scope, Order.updated_at, dialect, Order.status == "cancelled")
    )
    rate: Decimal | None = None
    if delivered:
        rate = (Decimal(returned) * Decimal(100) / Decimal(delivered)).quantize(
            _TWOPLACES, rounding=ROUND_HALF_UP
        )
    return DeliveryReport(
        filters=scope.filters(),
        delivered=delivered,
        returned=returned,
        returned_value=returned_value,
        cancelled=cancelled,
        return_rate_percent=rate,
    )


async def _count(db: AsyncSession, conds: list[Any]) -> int:
    return int(
        (await db.execute(select(func.count()).select_from(Order).where(*conds))).scalar_one()
    )


def choose_grain(scope: ReportScope, requested: str | None) -> ReportGrain:
    chosen: ReportGrain
    if requested == "day":
        chosen = "day"
    elif requested == "week":
        chosen = "week"
    elif requested == "month":
        chosen = "month"
    elif requested is not None:
        raise UnprocessableError("grain must be day, week, or month")
    else:
        days = (scope.date_to - scope.date_from).days + 1
        if days <= 31:
            chosen = "day"
        elif days <= 92:
            chosen = "week"
        else:
            chosen = "month"
    return chosen


async def trend_report(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> TrendReport:
    scope = await _scope(db, request, now)
    grain = choose_grain(scope, request.grain)
    dialect = dialect_name(db)
    days = await _trend_days(db, scope, dialect)
    points = [
        _trend_point(bucket, _fold(days, bucket, grain))
        for bucket in _buckets(scope.date_from, scope.date_to, grain)
    ]
    return TrendReport(filters=scope.filters(), grain=grain, points=points)


async def _trend_days(
    db: AsyncSession, scope: ReportScope, dialect: str
) -> dict[date, _DayFigures]:
    day = dhaka_day(Order.delivered_at, dialect)
    known = OrderItem.unit_cost.is_not(None)
    unknown = OrderItem.unit_cost.is_(None)
    line_rows = (
        await db.execute(
            _line_statement(
                scope,
                [
                    day,
                    func.coalesce(func.sum(OrderItem.line_total), 0),
                    func.sum(case((known, OrderItem.line_total))),
                    func.sum(case((known, OrderItem.quantity * OrderItem.unit_cost))),
                    func.coalesce(func.sum(case((unknown, OrderItem.line_total), else_=0)), 0),
                ],
                dialect,
            ).group_by(day)
        )
    ).all()
    figures: dict[date, _DayFigures] = {}
    for raw_day, merchandise, known_revenue, cost, unknown_revenue in line_rows:
        key = _as_date(raw_day)
        if key is None:
            continue
        parsed_cost = _money(cost)
        figures[key] = _DayFigures(
            merchandise=int(merchandise),
            known_revenue=int(known_revenue or 0),
            cost=parsed_cost or Decimal("0.00"),
            had_known=parsed_cost is not None,
            unknown_revenue=int(unknown_revenue),
        )
    ship_rows = (
        await db.execute(
            select(day, func.coalesce(func.sum(Order.shipping), 0))
            .select_from(Order)
            .where(*_order_filters(scope, Order.delivered_at, dialect, _realized_order_cond()))
            .group_by(day)
        )
    ).all()
    for raw_day, shipping in ship_rows:
        key = _as_date(raw_day)
        if key is None:
            continue
        bucket = figures.setdefault(key, _DayFigures())
        bucket.delivery += int(shipping)
    shares = _coupon_share_query(scope, dialect)
    coupon_rows = (
        await db.execute(
            select(
                shares.c.day,
                func.coalesce(func.sum(shares.c.matched), 0),
                func.coalesce(func.sum(shares.c.known), 0),
                func.coalesce(func.sum(shares.c.unknown), 0),
            ).group_by(shares.c.day)
        )
    ).all()
    for raw_day, matched, known_coupon, unknown_coupon in coupon_rows:
        key = _as_date(raw_day)
        if key is None:
            continue
        bucket = figures.setdefault(key, _DayFigures())
        bucket.coupon += _whole(matched)
        bucket.known_coupon += _whole(known_coupon)
        bucket.unknown_coupon += _whole(unknown_coupon)
    return figures


def _buckets(start: date, end: date, grain: str) -> list[date]:
    cursor = _bucket_of(start, grain)
    found: list[date] = []
    while cursor <= end:
        found.append(cursor)
        if grain == "week":
            cursor += timedelta(days=7)
        elif grain == "month":
            month = cursor.month + 1
            year = cursor.year + (month == 13)
            cursor = date(year, 1 if month == 13 else month, 1)
        else:
            cursor += timedelta(days=1)
    return found


def _bucket_of(day: date, grain: str) -> date:
    if grain == "week":
        return day - timedelta(days=day.weekday())
    if grain == "month":
        return day.replace(day=1)
    return day


def _fold(days: dict[date, _DayFigures], bucket: date, grain: str) -> _DayFigures:
    total = _DayFigures()
    for day, figures in days.items():
        if _bucket_of(day, grain) != bucket:
            continue
        total.merchandise += figures.merchandise
        total.delivery += figures.delivery
        total.known_revenue += figures.known_revenue
        total.cost += figures.cost
        total.had_known = total.had_known or figures.had_known
        total.unknown_revenue += figures.unknown_revenue
        total.coupon += figures.coupon
        total.known_coupon += figures.known_coupon
        total.unknown_coupon += figures.unknown_coupon
    return total


def _trend_point(bucket: date, figures: _DayFigures) -> TrendPoint:
    known_revenue = max(figures.known_revenue - figures.known_coupon, 0)
    unknown_revenue = max(figures.unknown_revenue - figures.unknown_coupon, 0)
    if figures.had_known:
        profit: Decimal | None = (Decimal(known_revenue) - figures.cost).quantize(
            _TWOPLACES, rounding=ROUND_HALF_UP
        )
    elif unknown_revenue:
        profit = None
    else:
        profit = Decimal("0.00")
    return TrendPoint(
        start=bucket,
        net_sales=figures.merchandise + figures.delivery - figures.coupon,
        profit=profit,
        unknown_cost_revenue=unknown_revenue,
    )


async def _product_analytics_period(
    db: AsyncSession,
    product_id: uuid.UUID,
    *,
    start: datetime | None,
    end: datetime | None,
) -> ProductAnalyticsPeriod:
    dialect = dialect_name(db)
    if start is not None and end is not None:
        delivered = and_(
            at_or_after(Order.delivered_at, start, dialect),
            before(Order.delivered_at, end, dialect),
            _realized_order_cond(),
        )
        returned = and_(
            at_or_after(Order.returned_at, start, dialect),
            before(Order.returned_at, end, dialect),
        )
    else:
        delivered = and_(Order.delivered_at.is_not(None), _realized_order_cond())
        returned = Order.returned_at.is_not(None)

    known = OrderItem.unit_cost.is_not(None)
    unknown = OrderItem.unit_cost.is_(None)
    order_merch = (
        select(
            OrderItem.order_id.label("order_id"),
            func.sum(OrderItem.line_total).label("merch"),
        )
        .group_by(OrderItem.order_id)
        .subquery()
    )
    discount = func.coalesce(Order.coupon_discount, 0) + func.coalesce(Order.manual_discount, 0)
    share = case(
        (
            and_(delivered, order_merch.c.merch > 0),
            _coupon_ratio(discount, OrderItem.line_total, order_merch.c.merch, dialect),
        ),
        else_=0,
    )
    known_share = case((and_(delivered, known), share), else_=0)

    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(case((delivered, OrderItem.quantity), else_=0)), 0),
                func.coalesce(func.sum(case((delivered, OrderItem.line_total), else_=0)), 0)
                - func.coalesce(func.sum(share), 0),
                func.sum(case((and_(delivered, known), OrderItem.line_total)))
                - func.coalesce(func.sum(known_share), 0),
                func.sum(case((and_(delivered, known), OrderItem.quantity * OrderItem.unit_cost))),
                func.coalesce(
                    func.sum(case((and_(delivered, unknown), OrderItem.quantity), else_=0)), 0
                ),
                func.count(distinct(case((returned, Order.id)))),
                func.coalesce(func.sum(case((returned, OrderItem.quantity), else_=0)), 0),
            )
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .outerjoin(order_merch, order_merch.c.order_id == Order.id)
            .where(OrderItem.product_id == product_id, or_(delivered, returned))
        )
    ).one()

    units_sold = int(row[0])
    revenue = _whole(row[1])
    known_rev = 0 if row[2] is None else max(_whole(row[2]), 0)
    cost = _money(row[3])
    unknown_units = int(row[4])
    return_count = int(row[5])
    returned_units = int(row[6])

    if cost is not None:
        cogs: Decimal | None = cost
        net_val = (Decimal(known_rev) - cost).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)
        profit: Decimal | None = net_val
        margin: Decimal | None = (
            (net_val * Decimal(100) / Decimal(known_rev)).quantize(
                _TWOPLACES, rounding=ROUND_HALF_UP
            )
            if known_rev > 0
            else None
        )
    elif unknown_units > 0:
        cogs, profit, margin = None, None, None
    else:
        cogs = Decimal("0.00")
        profit = Decimal("0.00")
        margin = None

    return ProductAnalyticsPeriod(
        units_sold=units_sold,
        revenue=revenue,
        cogs=cogs,
        profit=profit,
        is_loss=bool(profit is not None and profit < 0),
        margin_percent=margin,
        return_count=return_count,
        returned_units=returned_units,
        unknown_cost_units=unknown_units,
    )


async def product_analytics(
    db: AsyncSession, product_id: uuid.UUID, now: datetime | None = None
) -> ProductAnalyticsReport:
    product = await product_service.get_by_id(db, product_id)
    supplier_name: str | None = None
    if product.supplier_id is not None:
        supplier = await db.get(Supplier, product.supplier_id)
        if supplier is not None:
            supplier_name = supplier.name

    moment = (now or datetime.now(SHOP)).astimezone(SHOP)
    as_of = moment.date()
    since_30 = as_of - timedelta(days=29)
    start_30 = datetime(since_30.year, since_30.month, since_30.day, tzinfo=SHOP)
    end_30 = datetime(as_of.year, as_of.month, as_of.day, tzinfo=SHOP) + timedelta(days=1)

    lifetime = await _product_analytics_period(db, product.id, start=None, end=None)
    last_30 = await _product_analytics_period(db, product.id, start=start_30, end=end_30)
    movements = await inventory_service.list_movements(
        db, MovementQuery(product_id=product.id, page=1, page_size=20)
    )

    current_cost = _money(product.cost_price)
    stock_val: Decimal | None = None
    retail_val: Decimal | None = None
    if product.quantity is not None:
        retail_val = (Decimal(product.quantity) * Decimal(product.price)).quantize(
            _TWOPLACES, rounding=ROUND_HALF_UP
        )
        if current_cost is not None:
            stock_val = (Decimal(product.quantity) * current_cost).quantize(
                _TWOPLACES, rounding=ROUND_HALF_UP
            )

    return ProductAnalyticsReport(
        product_id=product.id,
        title=product.title,
        slug=product.slug,
        supplier_id=product.supplier_id,
        supplier_name=supplier_name,
        current_stock=product.quantity,
        current_cost_price=current_cost,
        selling_price=product.price,
        current_stock_value=stock_val,
        potential_retail_value=retail_val,
        lifetime=lifetime,
        last_30_days=last_30,
        recent_movements=movements.items,
    )


async def sales_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    summary = await sales_summary(db, request, now)
    scope = await _scope(db, request, now)
    rows = [
        [
            summary.order_count,
            summary.units_sold,
            summary.gross_sales,
            summary.discount,
            summary.coupon_discount,
            summary.manual_discount,
            summary.delivery_charge,
            summary.net_sales,
        ]
    ]
    headers = [
        "Order count",
        "Units sold",
        "Gross sales",
        "Discount",
        "Coupon discount",
        "Manual discount",
        "Delivery charge",
        "Net sales",
    ]
    return _filename("sales", scope), _book("Sales summary", scope, headers, rows, True)


async def profit_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    report = await profit_report(db, request, now)
    scope = await _scope(db, request, now)
    headers = [
        "Known revenue",
        "Cost",
        "Profit",
        "Loss amount",
        "Net profit",
        "Margin percent",
        "Unknown cost lines",
        "Unknown cost units",
        "Unknown cost revenue",
    ]
    rows = [
        [
            report.revenue,
            report.cost,
            report.profit,
            report.loss_amount,
            report.net_profit,
            report.margin_percent,
            report.unknown_cost_lines,
            report.unknown_cost_units,
            report.unknown_cost_revenue,
        ]
    ]
    return _filename("profit", scope), _book("Profit", scope, headers, rows, True)


async def profit_loss_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    report = await profit_loss_report(db, request, now)
    scope = await _scope(db, request, now)
    headers = [
        "Gross sales",
        "Product discount",
        "Coupon discount",
        "Manual discount",
        "Delivery charge",
        "Returned order value",
        "Net realized sales",
        "Total cost (COGS)",
        "Gross profit",
        "Loss amount",
        "Net profit",
        "Margin percent",
        "Collected amount",
        "Due amount",
        "Unknown cost lines",
        "Unknown cost units",
        "Unknown cost revenue",
    ]
    rows = [
        [
            report.gross_sales,
            report.product_discount,
            report.coupon_discount,
            report.manual_discount,
            report.delivery_charge,
            report.returned_order_value,
            report.net_realized_sales,
            report.total_cost,
            report.gross_profit,
            report.loss_amount,
            report.net_profit,
            report.margin_percent,
            report.collected_amount,
            report.due_amount,
            report.unknown_cost_lines,
            report.unknown_cost_units,
            report.unknown_cost_revenue,
        ]
    ]
    return _filename("profit-loss", scope), _book("Profit and Loss", scope, headers, rows, True)


async def product_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    scope = await _scope(db, request, now)
    sort = _parse_product_sort(request.sort)
    items, total = await _product_page(db, scope, offset=0, limit=MAX_EXPORT_ROWS, sort=sort)
    headers = [
        "Product id",
        "Title",
        "SKU",
        "Category",
        "Supplier",
        "Units sold",
        "Avg selling price",
        "Avg unit cost",
        "Current cost",
        "Current stock",
        "Stock value",
        "Revenue",
        "Cost",
        "Profit",
        "Is loss",
        "Margin percent",
        "Return count",
        "Returned units",
        "Return value",
        "Unknown cost units",
    ]
    rows = [
        [
            str(item.product_id or ""),
            item.title,
            item.sku,
            item.category_name,
            item.supplier_name or "",
            item.units_sold,
            item.avg_selling_price,
            item.unit_cost_avg,
            item.current_cost_price,
            item.current_stock,
            item.stock_value,
            item.revenue,
            item.cost,
            item.profit,
            1 if item.is_loss else 0,
            item.margin_percent,
            item.return_count,
            item.returned_units,
            item.return_value,
            item.unknown_cost_units,
        ]
        for item in items
    ]
    return _filename("products", scope), _book(
        "Products",
        scope,
        headers,
        rows,
        True,
        capped=total > len(items),
        extra=[["Sort", sort]],
    )


async def channel_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    report = await channel_report(db, request, now)
    scope = await _scope(db, request, now)
    headers = [
        "Breakdown",
        "Name",
        "Order count",
        "Units",
        "Net sales",
        "COGS",
        "Profit",
        "Margin percent",
        "Collected",
        "Due",
        "Unknown cost units",
    ]
    rows: list[list[object]] = []
    for ch in report.channels:
        rows.append(
            [
                "Origin",
                f"{ch.origin} ({ch.channel})",
                ch.order_count,
                ch.units,
                ch.net_sales,
                ch.cogs,
                ch.profit,
                ch.margin_percent,
                ch.collected,
                ch.due,
                ch.unknown_cost_units,
            ]
        )
    for pm in report.payment_methods:
        rows.append(
            [
                "Payment method",
                pm.payment_method,
                pm.order_count,
                pm.units,
                pm.net_sales,
                pm.cogs,
                pm.profit,
                pm.margin_percent,
                pm.collected,
                pm.due,
                pm.unknown_cost_units,
            ]
        )
    return _filename("channels", scope), _book("Channels and payments", scope, headers, rows, True)


async def supplier_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    report = await supplier_report(db, request, now)
    scope = await _scope(db, request, now)
    headers = [
        "Supplier id",
        "Supplier",
        "Linked products",
        "Purchases",
        "Purchased units",
        "Purchase spend",
        "Units sold",
        "Sales revenue",
        "COGS",
        "Net profit",
        "Margin percent",
        "Current stock units",
        "Current stock value",
    ]
    rows: list[list[object]] = [
        [
            str(item.supplier_id),
            item.supplier_name,
            item.linked_products_count,
            item.purchase_count,
            item.total_purchased_units,
            item.total_purchase_spend,
            item.units_sold,
            item.sales_revenue,
            item.cogs,
            item.net_profit,
            item.margin_percent,
            item.current_stock_units,
            item.current_stock_value,
        ]
        for item in report.items
    ]
    rows.append(
        [
            "",
            "Total",
            "",
            "",
            "",
            report.total_purchase_spend,
            "",
            report.total_sales_revenue,
            report.total_cogs,
            report.total_net_profit,
            "",
            "",
            "",
        ]
    )
    return _filename("suppliers", scope), _book("Suppliers performance", scope, headers, rows, True)


async def stock_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    scope = await _scope(db, request, now)
    moment = (now or datetime.now(SHOP)).astimezone(SHOP)
    as_of = moment.date()
    no_sale_since = as_of - timedelta(days=29)
    sale_start = datetime(no_sale_since.year, no_sale_since.month, no_sale_since.day, tzinfo=SHOP)
    sale_end = datetime(as_of.year, as_of.month, as_of.day, tzinfo=SHOP) + timedelta(days=1)
    items, total, summary = await _stock_page(
        db, scope, sale_start=sale_start, sale_end=sale_end, offset=0, limit=MAX_EXPORT_ROWS
    )
    headers = [
        "Product id",
        "Title",
        "Supplier",
        "Quantity",
        "Selling price",
        "Cost price",
        "Stock value",
        "Potential retail value",
        "Expected profit on hand",
        "Low stock",
        "No sale in 30 days",
    ]
    product_rows: list[list[object]] = [
        [
            str(item.product_id),
            item.title,
            item.supplier_name or "",
            item.quantity,
            item.selling_price,
            item.cost_price,
            item.stock_value,
            item.potential_retail_value,
            item.expected_profit_on_hand,
            1 if item.low_stock else 0,
            1 if item.no_sale_30d else 0,
        ]
        for item in items
    ]
    return _filename("stock", scope), _book(
        "Stock",
        scope,
        headers,
        product_rows,
        False,
        capped=total > len(items),
        extra=[
            ["As of", as_of.isoformat()],
            ["No sale since", no_sale_since.isoformat()],
            ["Units on hand", summary.units_on_hand],
            ["Stock value", summary.stock_value],
            ["Potential retail value", summary.potential_retail_value],
            ["Expected profit on hand", summary.expected_profit_on_hand],
            ["Missing cost count", summary.missing_cost_count],
            ["Unknown cost units", summary.unknown_cost_units],
            ["Low stock count", summary.low_stock_count],
            ["Low stock at", summary.low_stock_at],
            ["No sale in 30 days", summary.no_sale_30d_count],
            ["Note", "Stock figures are current. The date filter does not limit them."],
            [
                "Note",
                "Channel is ignored. No-sale uses delivered_at over the 30 days ending today.",
            ],
        ],
    )


async def movement_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    report = await movement_report(db, request, now)
    scope = await _scope(db, request, now)
    headers = [
        "Opening balance",
        "Opening",
        "Purchase",
        "Sale",
        "Return",
        "Cancel",
        "Adjustment",
        "Closing",
    ]
    rows = [
        [
            report.opening_balance,
            report.opening,
            report.purchase,
            report.sale,
            report.return_total,
            report.cancel,
            report.adjustment,
            report.closing,
        ]
    ]
    return _filename("movements", scope), _book(
        "Stock movements",
        scope,
        headers,
        rows,
        False,
        extra=[
            [
                "Note",
                "Sale is negative. Closing is the sum of every movement before the end date.",
            ]
        ],
    )


async def delivery_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    report = await delivery_report(db, request, now)
    scope = await _scope(db, request, now)
    headers = ["Delivered", "Returned", "Returned value", "Cancelled", "Return rate percent"]
    rows = [
        [
            report.delivered,
            report.returned,
            report.returned_value,
            report.cancelled,
            report.return_rate_percent,
        ]
    ]
    return _filename("delivery", scope), _book(
        "Delivery and returns",
        scope,
        headers,
        rows,
        True,
        extra=[
            [
                "Note",
                "Delivered uses delivered_at, returned uses returned_at, "
                "cancelled uses updated_at while status is cancelled.",
            ]
        ],
    )


async def trend_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    report = await trend_report(db, request, now)
    scope = await _scope(db, request, now)
    headers = ["Start", "Net sales", "Profit", "Unknown cost revenue"]
    rows = [
        [point.start.isoformat(), point.net_sales, point.profit, point.unknown_cost_revenue]
        for point in report.points
    ]
    return _filename("trend", scope), _book(
        "Trend",
        scope,
        headers,
        rows,
        True,
        extra=[["Grain", report.grain]],
    )


async def coupon_report(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> CouponReport:
    """Uses placed in the window. Cancelled redemptions are left out. Returns stay in."""
    scope = await _scope(db, request, now)
    dialect = dialect_name(db)
    stmt = (
        select(
            Coupon.id,
            Coupon.code,
            func.count(CouponRedemption.id),
            func.coalesce(func.sum(CouponRedemption.discount_amount), 0),
            func.coalesce(func.sum(Order.total), 0),
        )
        .select_from(Coupon)
        .join(CouponRedemption, CouponRedemption.coupon_id == Coupon.id)
        .join(Order, Order.id == CouponRedemption.order_id)
        .where(
            CouponRedemption.cancelled_at.is_(None),
            at_or_after(CouponRedemption.created_at, scope.start, dialect),
            before(CouponRedemption.created_at, scope.end, dialect),
        )
        .group_by(Coupon.id, Coupon.code)
        .order_by(
            func.coalesce(func.sum(CouponRedemption.discount_amount), 0).desc(),
            Coupon.code.asc(),
        )
    )
    if scope.origin is not None:
        stmt = stmt.where(Order.origin == scope.origin)
    rows = (await db.execute(stmt)).all()
    items = [
        CouponReportRow(
            coupon_id=row[0],
            code=str(row[1]),
            times_used=int(row[2]),
            total_discount=int(row[3]),
            total_sales=int(row[4]),
        )
        for row in rows
    ]
    return CouponReport(
        filters=scope.filters(channel_applies=False),
        items=items,
        times_used=sum(item.times_used for item in items),
        total_discount=sum(item.total_discount for item in items),
        total_sales=sum(item.total_sales for item in items),
    )


async def coupon_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    report = await coupon_report(db, request, now)
    scope = await _scope(db, request, now)
    headers = ["Code", "Times used", "Total discount", "Total sales"]
    rows: list[list[object]] = [
        [item.code, item.times_used, item.total_discount, item.total_sales] for item in report.items
    ]
    rows.append(["Total", report.times_used, report.total_discount, report.total_sales])
    return _filename("coupons", scope), _book(
        "Coupons",
        scope,
        headers,
        rows,
        False,
        extra=[
            [
                "Note",
                "Counts active redemptions placed in the window. "
                "Cancelled orders are omitted. Returned orders stay. "
                "Total sales is the order total after the coupon, including delivery.",
            ]
        ],
    )


def _book(
    title: str,
    scope: ReportScope,
    headers: list[str],
    rows: Sequence[Sequence[object]],
    channel_applies: bool,
    *,
    capped: bool = False,
    extra: list[list[object]] | None = None,
) -> bytes:
    preamble: list[list[object]] = [
        ["Report", title],
        ["Timezone", "Asia/Dhaka"],
        ["From", scope.date_from.isoformat()],
        ["To", scope.date_to.isoformat()],
        ["Preset", scope.preset or ""],
        ["Product", str(scope.product_id) if scope.product_id else ""],
        ["Category", str(scope.category_id) if scope.category_id else ""],
        ["Supplier", str(scope.supplier_id) if scope.supplier_id else ""],
        ["Channel", scope.channel or ""],
        ["Origin", scope.origin or ""],
        ["Profit filter", scope.profit_filter or ""],
        ["Channel applies", "yes" if channel_applies else "no"],
    ]
    if capped:
        preamble.append(["Note", f"Export stopped at {MAX_EXPORT_ROWS} rows"])
    preamble.extend(extra or [])
    preamble.append([None])
    return workbook_bytes(headers, rows, title, preamble)


def _filename(kind: str, scope: ReportScope) -> str:
    return f"{kind}-{scope.date_from.isoformat()}-to-{scope.date_to.isoformat()}.xlsx"


def _money(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(_TWOPLACES, rounding=ROUND_HALF_UP)


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _uuid(value: object) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
