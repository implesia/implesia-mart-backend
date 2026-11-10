"""Admin sales, profit, stock, and delivery reports.

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

from sqlalchemy import String, and_, case, cast, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.inventory import StockMovement
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.schemas.common import page_count
from app.schemas.report import (
    DeliveryReport,
    MovementReport,
    ProductReport,
    ProductReportRow,
    ProfitReport,
    ReportFilters,
    ReportGrain,
    SalesSummary,
    StockReport,
    StockRow,
    StockSummary,
    TrendPoint,
    TrendReport,
)
from app.services.category_service import load_index
from app.services.inventory_excel import MAX_EXPORT_ROWS, workbook_bytes
from app.services.shop_sql import SHOP, at_or_after, before, dhaka_day, dialect_name

PRESETS = ("this_week", "this_month", "last_month")
LOW_STOCK_AT = 5
_TWOPLACES = Decimal("0.01")


@dataclass(frozen=True)
class ReportRequest:
    preset: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    product_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    channel: str | None = None
    grain: str | None = None


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
    channel: str | None

    def filters(self, *, channel_applies: bool = True) -> ReportFilters:
        return ReportFilters(
            preset=self.preset,
            date_from=self.date_from,
            date_to=self.date_to,
            product_id=self.product_id,
            category_id=self.category_id,
            channel=self.channel,
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
            raise UnprocessableError("preset must be this_week, this_month, or last_month")
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
    if preset == "this_week":
        return today - timedelta(days=today.weekday()), today
    if preset == "this_month":
        return today.replace(day=1), today
    first_this_month = today.replace(day=1)
    last_previous = first_this_month - timedelta(days=1)
    return last_previous.replace(day=1), last_previous


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
    return ReportScope(
        start=start,
        end=end,
        date_from=start_day,
        date_to=end_day,
        preset=preset,
        product_id=request.product_id,
        category_id=request.category_id,
        category_ids=category_ids,
        channel=channel,
    )


def _matching_line(scope: ReportScope) -> Any | None:
    if scope.product_id is None and scope.category_ids is None:
        return None
    stmt = select(OrderItem.id).where(OrderItem.order_id == Order.id)
    if scope.product_id is not None:
        stmt = stmt.where(OrderItem.product_id == scope.product_id)
    if scope.category_ids is not None:
        stmt = stmt.join(Product, Product.id == OrderItem.product_id).where(
            Product.category_id.in_(scope.category_ids)
        )
    return stmt.exists()


def _order_filters(
    scope: ReportScope, moment: Any, dialect: str, *extra: Any
) -> list[Any]:
    conds: list[Any] = [
        at_or_after(moment, scope.start, dialect),
        before(moment, scope.end, dialect),
        *extra,
    ]
    if scope.channel is not None:
        conds.append(Order.channel == scope.channel)
    matched = _matching_line(scope)
    if matched is not None:
        conds.append(matched)
    return conds


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
    ]
    if scope.channel is not None:
        conds.append(Order.channel == scope.channel)
    if scope.product_id is not None:
        conds.append(OrderItem.product_id == scope.product_id)
    if scope.category_ids is not None:
        conds.append(Product.category_id.in_(scope.category_ids))
    return stmt.where(*conds)


async def _order_shipping(db: AsyncSession, scope: ReportScope) -> tuple[int, int]:
    count, shipping = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Order.shipping), 0))
            .select_from(Order)
            .where(*_order_filters(scope, Order.delivered_at, dialect_name(db)))
        )
    ).one()
    return int(count), int(shipping)


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


async def sales_summary(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> SalesSummary:
    scope = await _scope(db, request, now)
    orders, shipping = await _order_shipping(db, scope)
    totals = await _line_totals(db, scope)
    discount = totals.gross - totals.merchandise
    return SalesSummary(
        filters=scope.filters(),
        order_count=orders,
        units_sold=totals.units,
        gross_sales=totals.gross,
        discount=discount,
        delivery_charge=shipping,
        net_sales=totals.merchandise + shipping,
    )


async def profit_report(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> ProfitReport:
    scope = await _scope(db, request, now)
    totals = await _line_totals(db, scope)
    profit, margin = _profit_of(totals)
    return ProfitReport(
        filters=scope.filters(),
        revenue=totals.known_revenue,
        cost=totals.cost,
        profit=profit,
        margin_percent=margin,
        unknown_cost_lines=totals.unknown_lines,
        unknown_cost_units=totals.unknown_units,
        unknown_cost_revenue=totals.unknown_revenue,
    )


def _product_groups(scope: ReportScope, dialect: str) -> Any:
    delivered = and_(
        at_or_after(Order.delivered_at, scope.start, dialect),
        before(Order.delivered_at, scope.end, dialect),
    )
    returned = and_(
        at_or_after(Order.returned_at, scope.start, dialect),
        before(Order.returned_at, scope.end, dialect),
    )
    known = OrderItem.unit_cost.is_not(None)
    group_key = func.coalesce(cast(OrderItem.product_id, String), OrderItem.title)
    stmt = (
        select(
            func.max(cast(OrderItem.product_id, String)).label("product_id"),
            func.max(func.coalesce(Product.title, OrderItem.title)).label("title"),
            func.coalesce(func.sum(case((delivered, OrderItem.quantity), else_=0)), 0).label(
                "units_sold"
            ),
            func.coalesce(func.sum(case((delivered, OrderItem.line_total), else_=0)), 0).label(
                "revenue"
            ),
            func.sum(case((and_(delivered, known), OrderItem.line_total))).label("known_revenue"),
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
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .where(or_(delivered, returned))
        .group_by(group_key)
    )
    if scope.channel is not None:
        stmt = stmt.where(Order.channel == scope.channel)
    if scope.product_id is not None:
        stmt = stmt.where(OrderItem.product_id == scope.product_id)
    if scope.category_ids is not None:
        stmt = stmt.where(Product.category_id.in_(scope.category_ids))
    return stmt


def _product_row(row: Any) -> ProductReportRow:
    known_revenue = row.known_revenue
    cost = _money(row.cost)
    revenue = int(row.revenue)
    if cost is None:
        profit, margin = None, None
    else:
        known = int(known_revenue or 0)
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
        units_sold=int(row.units_sold),
        revenue=revenue,
        cost=cost,
        profit=profit,
        margin_percent=margin,
        return_count=int(row.return_count),
        unknown_cost_units=int(row.unknown_units),
    )


async def _product_page(
    db: AsyncSession, scope: ReportScope, *, offset: int, limit: int
) -> tuple[list[ProductReportRow], int]:
    grouped = _product_groups(scope, dialect_name(db)).subquery()
    total = int((await db.scalar(select(func.count()).select_from(grouped))) or 0)
    rows = (
        await db.execute(
            select(grouped)
            .order_by(grouped.c.revenue.desc(), grouped.c.units_sold.desc(), grouped.c.title.asc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
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
    items, total = await _product_page(
        db, scope, offset=(page - 1) * page_size, limit=page_size
    )
    return ProductReport(
        filters=scope.filters(),
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=page_count(total, page_size),
    )


def _no_sale(start: datetime, end: datetime, dialect: str) -> Any:
    return ~(
        select(OrderItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            OrderItem.product_id == Product.id,
            at_or_after(Order.delivered_at, start, dialect),
            before(Order.delivered_at, end, dialect),
        )
        .exists()
    )


def _stock_filters(scope: ReportScope) -> list[Any]:
    conds: list[Any] = []
    if scope.product_id is not None:
        conds.append(Product.id == scope.product_id)
    if scope.category_ids is not None:
        conds.append(Product.category_id.in_(scope.category_ids))
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
    low_col = case((low, 1), else_=0).label("low_stock")
    idle_col = case((no_sale, 1), else_=0).label("no_sale_30d")
    listed = (
        select(
            Product.id,
            Product.title,
            Product.quantity,
            Product.cost_price,
            value_col,
            low_col,
            idle_col,
        )
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
            cost_price=_money(row.cost_price),
            stock_value=_money(row.stock_value),
            low_stock=bool(row.low_stock),
            no_sale_30d=bool(row.no_sale_30d),
        )
        for row in rows
    ]
    summary = StockSummary(
        product_count=int(summary_row[0]),
        units_on_hand=int(summary_row[1]),
        stock_value=_money(summary_row[2]) or Decimal("0.00"),
        unknown_cost_units=int(summary_row[3]),
        low_stock_count=int(summary_row[4]),
        low_stock_at=LOW_STOCK_AT,
        no_sale_30d_count=int(summary_row[5]),
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
    if scope.category_ids is not None:
        stmt = stmt.join(Product, Product.id == StockMovement.product_id)
    stmt = stmt.where(before_end)
    if scope.product_id is not None:
        stmt = stmt.where(StockMovement.product_id == scope.product_id)
    if scope.category_ids is not None:
        stmt = stmt.where(Product.category_id.in_(scope.category_ids))
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
    returned = await _count(db, _order_filters(scope, Order.returned_at, dialect))
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
            .where(*_order_filters(scope, Order.delivered_at, dialect))
            .group_by(day)
        )
    ).all()
    for raw_day, shipping in ship_rows:
        key = _as_date(raw_day)
        if key is None:
            continue
        bucket = figures.setdefault(key, _DayFigures())
        bucket.delivery += int(shipping)
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
    return total


def _trend_point(bucket: date, figures: _DayFigures) -> TrendPoint:
    if figures.had_known:
        profit: Decimal | None = (Decimal(figures.known_revenue) - figures.cost).quantize(
            _TWOPLACES, rounding=ROUND_HALF_UP
        )
    elif figures.unknown_revenue:
        profit = None
    else:
        profit = Decimal("0.00")
    return TrendPoint(
        start=bucket,
        net_sales=figures.merchandise + figures.delivery,
        profit=profit,
        unknown_cost_revenue=figures.unknown_revenue,
    )


async def sales_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    summary = await sales_summary(db, request, now)
    scope = await _scope(db, request, now)
    rows = [[
        summary.order_count,
        summary.units_sold,
        summary.gross_sales,
        summary.discount,
        summary.delivery_charge,
        summary.net_sales,
    ]]
    headers = [
        "Order count",
        "Units sold",
        "Gross sales",
        "Discount",
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
        "Margin percent",
        "Unknown cost lines",
        "Unknown cost units",
        "Unknown cost revenue",
    ]
    rows = [[
        report.revenue,
        report.cost,
        report.profit,
        report.margin_percent,
        report.unknown_cost_lines,
        report.unknown_cost_units,
        report.unknown_cost_revenue,
    ]]
    return _filename("profit", scope), _book("Profit", scope, headers, rows, True)


async def product_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    scope = await _scope(db, request, now)
    items, total = await _product_page(db, scope, offset=0, limit=MAX_EXPORT_ROWS)
    headers = [
        "Product id",
        "Title",
        "Units sold",
        "Revenue",
        "Cost",
        "Profit",
        "Margin percent",
        "Return count",
        "Unknown cost units",
    ]
    rows = [
        [
            str(item.product_id or ""),
            item.title,
            item.units_sold,
            item.revenue,
            item.cost,
            item.profit,
            item.margin_percent,
            item.return_count,
            item.unknown_cost_units,
        ]
        for item in items
    ]
    return _filename("products", scope), _book(
        "Products", scope, headers, rows, True, capped=total > len(items)
    )


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
        "Quantity",
        "Cost price",
        "Stock value",
        "Low stock",
        "No sale in 30 days",
    ]
    product_rows: list[list[object]] = [
        [
            str(item.product_id),
            item.title,
            item.quantity,
            item.cost_price,
            item.stock_value,
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
    rows = [[
        report.opening_balance,
        report.opening,
        report.purchase,
        report.sale,
        report.return_total,
        report.cancel,
        report.adjustment,
        report.closing,
    ]]
    return _filename("movements", scope), _book(
        "Stock movements",
        scope,
        headers,
        rows,
        False,
        extra=[[
            "Note",
            "Sale is negative. Closing is the sum of every movement before the end date.",
        ]],
    )


async def delivery_workbook(
    db: AsyncSession, request: ReportRequest, now: datetime | None = None
) -> tuple[str, bytes]:
    report = await delivery_report(db, request, now)
    scope = await _scope(db, request, now)
    headers = ["Delivered", "Returned", "Cancelled", "Return rate percent"]
    rows = [[report.delivered, report.returned, report.cancelled, report.return_rate_percent]]
    return _filename("delivery", scope), _book(
        "Delivery and returns",
        scope,
        headers,
        rows,
        True,
        extra=[[
            "Note",
            "Delivered uses delivered_at, returned uses returned_at, "
            "cancelled uses updated_at while status is cancelled.",
        ]],
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
        ["Channel", scope.channel or ""],
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
