"""Shop overview for the admin dashboard.

Figures are SQL aggregates. Revenue leaves out cancelled and returned orders
and follows ordered_at when set, otherwise the creation time. "Delivered" counts orders whose
delivered_at falls in the window, including an order that was later returned.
Customers are unique checkout phones. "Today" is compared with the same hours
of yesterday in Asia/Dhaka.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import String, case, cast, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import UnprocessableError
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.schemas.dashboard import (
    DashboardArea,
    DashboardCategory,
    DashboardGrain,
    DashboardMetric,
    DashboardOverview,
    DashboardPoint,
    DashboardRange,
    DashboardRecentOrder,
    DashboardSeller,
    DashboardStatusSlice,
    DashboardTrend,
)
from app.services.category_service import CategoryIndex, load_index
from app.services.shop_sql import SHOP, at_or_after, before, dhaka_day, dhaka_hour, dialect_name

STATUSES = ("new", "confirmed", "packed", "shipped", "delivered", "cancelled", "returned")
# Offline orders carry the counter date in ordered_at. Online rows leave it empty.
_PLACED = func.coalesce(Order.ordered_at, Order.created_at)
_NOT_SALE = ("cancelled", "returned")
MAX_DAYS = 366
_GRAIN_LABEL = {"hour": "Hourly", "day": "Daily", "week": "Weekly", "month": "Monthly"}
DISTRICTS = (
    ("Dhaka", ("ঢাকা", "dhaka")),
    ("Chattogram", ("চট্টগ্রাম", "chattogram", "chittagong")),
    ("Rajshahi", ("রাজশাহী", "rajshahi")),
    ("Khulna", ("খুলনা", "khulna")),
    ("Sylhet", ("সিলেট", "sylhet")),
    ("Barishal", ("বরিশাল", "barishal", "barisal")),
    ("Rangpur", ("রংপুর", "rangpur")),
    ("Mymensingh", ("ময়মনসিংহ", "mymensingh")),
    ("Gazipur", ("গাজীপুর", "gazipur")),
    ("Narayanganj", ("নারায়ণগঞ্জ", "narayanganj")),
    ("Cumilla", ("কুমিল্লা", "cumilla", "comilla")),
)


@dataclass(frozen=True)
class _Window:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class _Metrics:
    orders: int
    revenue: int
    sales: int
    customers: int
    pending: int
    delivered: int


async def overview(
    db: AsyncSession,
    span: DashboardRange,
    start: date | None,
    end: date | None,
    now: datetime | None = None,
) -> DashboardOverview:
    moment = (now or datetime.now(SHOP)).astimezone(SHOP)
    current = _window(span, start, end, moment)
    previous = _previous(current, span, moment)
    grain = _grain(current)
    index = await load_index(db)
    dialect = dialect_name(db)
    current_metrics = await _metrics(db, current, dialect)
    previous_metrics = await _metrics(db, previous, dialect)
    series_end = current.end
    if grain == "hour" and current.start <= moment < current.end:
        series_end = min(current.end, _next_hour(moment))
    current_groups, step = await _grouped(db, current.start, series_end, grain, dialect)
    previous_groups, _step = await _grouped(db, previous.start, previous.end, grain, dialect)
    series = _series(
        current, previous, grain, moment, current_groups, previous_groups, step
    )
    return DashboardOverview(
        range=span,
        period_label=_span_label(current),
        comparison_label=f"vs {_span_label(previous)}",
        grain=grain,
        grain_label=_GRAIN_LABEL[grain],
        revenue=_metric(
            current_metrics.revenue,
            _taka(current_metrics.revenue),
            previous_metrics.revenue,
            [point.revenue for point in series],
        ),
        orders=_metric(
            current_metrics.orders,
            str(current_metrics.orders),
            previous_metrics.orders,
            [point.orders for point in series],
        ),
        customers=_metric(
            current_metrics.customers,
            str(current_metrics.customers),
            previous_metrics.customers,
            [],
        ),
        average_order=_metric(
            _average(current_metrics.revenue, current_metrics.sales),
            _taka(_average(current_metrics.revenue, current_metrics.sales)),
            _average(previous_metrics.revenue, previous_metrics.sales),
            [],
        ),
        pending=_metric(
            current_metrics.pending, str(current_metrics.pending), previous_metrics.pending, []
        ),
        delivered=_metric(
            current_metrics.delivered,
            str(current_metrics.delivered),
            previous_metrics.delivered,
            [],
        ),
        series=series,
        statuses=await _statuses(db, current),
        order_count=current_metrics.orders,
        best_sellers=await _sellers(db, current, index),
        recent=await _recent_orders(db, current),
        areas=await _areas(db, current, current_metrics.orders),
        categories=await _categories(db, current, index),
    )


async def _metrics(db: AsyncSession, window: _Window, dialect: str) -> _Metrics:
    sale = Order.status.notin_(_NOT_SALE)
    key = _customer_key(dialect)
    row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((sale, Order.total), else_=0)), 0),
                func.coalesce(func.sum(case((sale, 1), else_=0)), 0),
                func.count(distinct(key)),
                func.coalesce(func.sum(case((Order.status == "new", 1), else_=0)), 0),
            ).where(
                at_or_after(_PLACED, window.start, dialect),
                before(_PLACED, window.end, dialect),
            )
        )
    ).one()
    delivered = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Order)
                .where(
                    at_or_after(Order.delivered_at, window.start, dialect),
                    before(Order.delivered_at, window.end, dialect),
                )
            )
        ).scalar_one()
    )
    return _Metrics(
        orders=int(row[0]),
        revenue=int(row[1]),
        sales=int(row[2]),
        customers=int(row[3]),
        pending=int(row[4]),
        delivered=delivered,
    )


def _customer_key(dialect: str) -> Any:
    digits: Any
    if dialect == "postgresql":
        digits = func.regexp_replace(Order.phone, r"[^0-9]", "", "g")
        tail = func.right(digits, 11)
    else:
        digits = Order.phone
        for character in (" ", "-", "(", ")", "+", "."):
            digits = func.replace(digits, character, "")
        tail = func.substr(digits, -11)
    name = func.lower(func.trim(Order.customer_name))
    return case((func.length(digits) >= 11, tail), else_=name)


async def _grouped(
    db: AsyncSession,
    start: datetime,
    end: datetime,
    grain: DashboardGrain,
    dialect: str,
) -> tuple[list[tuple[datetime, int, int]], timedelta]:
    hourly = grain == "hour"
    key = dhaka_hour(_PLACED, dialect) if hourly else dhaka_day(_PLACED, dialect)
    step = timedelta(hours=1) if hourly else timedelta(days=1)
    sale_total = case((Order.status.notin_(_NOT_SALE), Order.total), else_=0)
    rows = (
        await db.execute(
            select(key, func.count(), func.coalesce(func.sum(sale_total), 0))
            .where(
                at_or_after(_PLACED, start, dialect),
                before(_PLACED, end, dialect),
            )
            .group_by(key)
        )
    ).all()
    parsed: list[tuple[datetime, int, int]] = []
    for raw, orders, revenue in rows:
        moment = _parse_group(raw, hour=hourly)
        if moment is None:
            continue
        parsed.append((moment, int(orders), int(revenue)))
    return parsed, step


def _parse_group(value: object, *, hour: bool) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        local = value.replace(tzinfo=SHOP) if value.tzinfo is None else value.astimezone(SHOP)
        if hour:
            return local.replace(minute=0, second=0, microsecond=0)
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=SHOP)
    text = str(value).strip().replace("T", " ")
    if not text:
        return None
    if hour or len(text) > 10:
        parsed = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        return parsed.replace(tzinfo=SHOP)
    parsed_day = date.fromisoformat(text[:10])
    return datetime(parsed_day.year, parsed_day.month, parsed_day.day, tzinfo=SHOP)


def _series(
    current: _Window,
    previous: _Window,
    grain: DashboardGrain,
    now: datetime,
    current_groups: list[tuple[datetime, int, int]],
    previous_groups: list[tuple[datetime, int, int]],
    step: timedelta,
) -> list[DashboardPoint]:
    end = current.end
    if grain == "hour" and current.start <= now < current.end:
        end = min(current.end, _next_hour(now))
    points: list[DashboardPoint] = []
    for index, bucket in enumerate(_buckets(current.start, end, grain)):
        duration = bucket.end - bucket.start
        earlier = _shift(previous.start, index, grain)
        revenue, orders = _overlap(current_groups, bucket, step)
        previous_revenue, _previous_orders = _overlap(
            previous_groups, _Window(earlier, earlier + duration), step
        )
        points.append(
            DashboardPoint(
                label=_bucket_label(bucket.start, grain),
                revenue=revenue,
                orders=orders,
                previous_revenue=previous_revenue,
            )
        )
    return points


def _overlap(
    groups: list[tuple[datetime, int, int]], bucket: _Window, step: timedelta
) -> tuple[int, int]:
    revenue = 0
    orders = 0
    for moment, count, money in groups:
        if moment < bucket.end and moment + step > bucket.start:
            orders += count
            revenue += money
    return revenue, orders


async def _statuses(db: AsyncSession, window: _Window) -> list[DashboardStatusSlice]:
    rows = (
        await db.execute(
            select(Order.status, func.count()).where(
                at_or_after(_PLACED, window.start, dialect_name(db)),
                before(_PLACED, window.end, dialect_name(db)),
            ).group_by(Order.status)
        )
    ).all()
    counts = {str(status): int(count) for status, count in rows}
    total = sum(counts.values())
    return [
        DashboardStatusSlice(
            status=status, count=counts.get(status, 0), share=_share(counts.get(status, 0), total)
        )
        for status in STATUSES
    ]


async def _sellers(
    db: AsyncSession, window: _Window, index: CategoryIndex
) -> list[DashboardSeller]:
    key = func.coalesce(cast(OrderItem.product_id, String), OrderItem.slug)
    image = func.coalesce(func.nullif(Product.image_src, ""), OrderItem.image_src)
    rows = (
        await db.execute(
            select(
                func.max(cast(OrderItem.product_id, String)),
                func.max(func.coalesce(Product.slug, OrderItem.slug)),
                func.max(func.coalesce(Product.title, OrderItem.title)),
                func.max(image),
                func.max(cast(Product.category_id, String)),
                func.max(Product.quantity),
                func.max(Product.status),
                func.coalesce(func.sum(OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.line_total), 0),
            )
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .outerjoin(Product, Product.id == OrderItem.product_id)
            .where(
                at_or_after(_PLACED, window.start, dialect_name(db)),
                before(_PLACED, window.end, dialect_name(db)),
                Order.status.notin_(_NOT_SALE),
            )
            .group_by(key)
            .order_by(func.sum(OrderItem.line_total).desc(), func.sum(OrderItem.quantity).desc())
            .limit(5)
        )
    ).all()
    sellers: list[DashboardSeller] = []
    for product_id, slug, title, image_src, category_id, quantity, status, units, revenue in rows:
        category = _category_name(_uuid(category_id), index)
        sellers.append(
            DashboardSeller(
                product_id=_uuid(product_id),
                slug=str(slug or ""),
                title=str(title or ""),
                image_src=str(image_src or ""),
                category=category,
                units=int(units),
                revenue=int(revenue),
                stock_label=_stock_label(
                    int(quantity) if quantity is not None else None,
                    str(status) if status is not None else None,
                ),
            )
        )
    return sellers


async def _recent_orders(db: AsyncSession, window: _Window) -> list[DashboardRecentOrder]:
    rows = list(
        (
            await db.scalars(
                select(Order)
                .where(
                    at_or_after(_PLACED, window.start, dialect_name(db)),
                    before(_PLACED, window.end, dialect_name(db)),
                )
                .options(selectinload(Order.items))
                .order_by(Order.created_at.desc())
                .limit(6)
            )
        )
        .unique()
        .all()
    )
    return _recent(rows)


async def _areas(db: AsyncSession, window: _Window, total: int) -> list[DashboardArea]:
    name = _area_expr()
    money = case((Order.status.notin_(_NOT_SALE), Order.total), else_=0)
    rows = (
        await db.execute(
            select(name, func.count(), func.coalesce(func.sum(money), 0))
            .where(
                at_or_after(_PLACED, window.start, dialect_name(db)),
                before(_PLACED, window.end, dialect_name(db)),
            )
            .group_by(name)
            .order_by(func.count().desc(), func.sum(money).desc())
            .limit(6)
        )
    ).all()
    return [
        DashboardArea(
            name=str(label),
            orders=int(count),
            revenue=int(revenue),
            share=_share(int(count), total),
        )
        for label, count, revenue in rows
    ]


def _area_expr() -> Any:
    district = func.lower(func.trim(Order.district))
    area = func.lower(func.trim(Order.area))
    whens = []
    for label, keys in DISTRICTS:
        folded = tuple(key.casefold() for key in keys)
        whens.append((or_(district.in_(folded), area.in_(folded)), label))
    fallback = func.coalesce(
        func.nullif(func.trim(Order.district), ""),
        func.nullif(func.trim(Order.area), ""),
        "Unknown area",
    )
    return case(*whens, else_=fallback)


async def _categories(
    db: AsyncSession, window: _Window, index: CategoryIndex
) -> list[DashboardCategory]:
    rows = (
        await db.execute(
            select(
                Product.category_id,
                func.coalesce(func.sum(OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.line_total), 0),
            )
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .join(Product, Product.id == OrderItem.product_id)
            .where(
                at_or_after(_PLACED, window.start, dialect_name(db)),
                before(_PLACED, window.end, dialect_name(db)),
                Order.status.notin_(_NOT_SALE),
                Product.category_id.is_not(None),
            )
            .group_by(Product.category_id)
        )
    ).all()
    rolled: dict[str, list[int]] = {}
    for category_id, units, revenue in rows:
        root = index.root_of(category_id)
        if root is None:
            continue
        current_units, current_revenue = rolled.get(root.slug, [0, 0])
        rolled[root.slug] = [current_units + int(units), current_revenue + int(revenue)]
    total = sum(revenue for _, revenue in rolled.values())
    categories = [
        DashboardCategory(
            id=slug,
            label=index.by_slug[slug].name,
            revenue=revenue,
            units=units,
            share=_share(revenue, total),
        )
        for slug, (units, revenue) in rolled.items()
    ]
    categories.sort(key=lambda row: row.revenue, reverse=True)
    return categories


def _recent(orders: list[Order]) -> list[DashboardRecentOrder]:
    newest = sorted(orders, key=lambda order: _aware(order.created_at), reverse=True)[:6]
    return [
        DashboardRecentOrder(
            id=order.id,
            number=order.number,
            created_at=_aware(order.created_at),
            status=order.status,
            customer_name=order.customer_name,
            items_label=_items_label(order),
            total=order.total,
            payment_method=order.payment_method,
        )
        for order in newest
    ]


def _items_label(order: Order) -> str:
    if not order.items:
        return "—"
    extra = len(order.items) - 1
    title = order.items[0].title
    return f"{title} +{extra}" if extra else title


def _stock_label(quantity: int | None, status: str | None) -> str:
    if status is None or status == "available":
        if quantity is not None:
            return f"{quantity} in stock"
        return "In stock"
    if status == "sold-out":
        return "Sold out"
    return "Coming soon"


def _category_name(category_id: uuid.UUID | None, index: CategoryIndex) -> str:
    row = index.by_id.get(category_id) if category_id is not None else None
    return row.name if row is not None else "Uncategorized"


def _uuid(value: object) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _window(span: DashboardRange, start: date | None, end: date | None, now: datetime) -> _Window:
    today = _day(now)
    if span == "today":
        return _Window(today, _shift_days(today, 1))
    if span == "yesterday":
        return _Window(_shift_days(today, -1), today)
    if span == "7d":
        return _Window(_shift_days(today, -6), _shift_days(today, 1))
    if span == "30d":
        return _Window(_shift_days(today, -29), _shift_days(today, 1))
    if span == "this-month":
        return _Window(today.replace(day=1), _shift_days(today, 1))
    if span == "last-month":
        first = today.replace(day=1)
        return _Window(_month_start(first, -1), first)
    if start is None or end is None:
        raise UnprocessableError("Choose a start and end date")
    first_day, last_day = (start, end) if start <= end else (end, start)
    if (last_day - first_day).days + 1 > MAX_DAYS:
        raise UnprocessableError("Choose a range of 366 days or less")
    return _Window(_day_on(first_day), _shift_days(_day_on(last_day), 1))


def _previous(current: _Window, span: DashboardRange, now: datetime) -> _Window:
    if span == "today":
        elapsed = _elapsed(current, now)
        start = _shift_days(current.start, -1)
        return _Window(start, start + elapsed)
    if span == "this-month":
        start = _month_start(current.start, -1)
        elapsed = _elapsed(current, now)
        end = min(start + elapsed, current.start)
        return _Window(start, end)
    return _Window(current.start - (current.end - current.start), current.start)


def _elapsed(current: _Window, now: datetime) -> timedelta:
    clipped = min(max(now, current.start), current.end)
    return clipped - current.start


def _grain(window: _Window) -> DashboardGrain:
    days = (window.end - window.start).total_seconds() / 86_400
    if days <= 2:
        return "hour"
    if days <= 62:
        return "day"
    if days <= 180:
        return "week"
    return "month"


def _buckets(start: datetime, end: datetime, grain: DashboardGrain) -> list[_Window]:
    cursor = _align(start, grain)
    buckets: list[_Window] = []
    while cursor < end and len(buckets) < 400:
        nxt = _step(cursor, grain)
        buckets.append(_Window(max(cursor, start), min(nxt, end)))
        cursor = nxt
    return buckets or [_Window(start, end)]


def _metric(value: int, display: str, previous: int, sparkline: list[int]) -> DashboardMetric:
    return DashboardMetric(
        value=value,
        display=display,
        trend=_trend(value, previous),
        sparkline=sparkline,
    )


def _trend(current: int, previous: int) -> DashboardTrend:
    if previous == 0 and current == 0:
        return DashboardTrend(direction="flat", text="0%")
    if previous == 0:
        return DashboardTrend(direction="new", text="New")
    percent = _half_up((current - previous) / previous * 100, 1)
    if abs(percent) < 0.05:
        return DashboardTrend(direction="flat", text="0%")
    text = f"{abs(percent):g}%"
    return DashboardTrend(direction="up" if percent > 0 else "down", text=text)


def _share(part: int, total: int) -> float:
    if total <= 0:
        return 0
    return _half_up(part / total * 100, 1)


def _average(revenue: int, count: int) -> int:
    if count <= 0:
        return 0
    return int(revenue / count + 0.5)


def _half_up(value: float, places: int) -> float:
    factor = 10**places
    shifted = value * factor
    rounded = int(shifted + (0.5 if shifted >= 0 else -0.5))
    return rounded / factor


def _taka(value: int) -> str:
    return f"৳{value:,}"


def _span_label(window: _Window) -> str:
    last = window.end - timedelta(microseconds=1)
    if window.start.astimezone(SHOP).date() == last.astimezone(SHOP).date():
        return _day_label(window.start)
    return f"{_day_label(window.start)} – {_day_label(last)}"


def _day_label(moment: datetime) -> str:
    local = moment.astimezone(SHOP)
    return f"{local:%b} {local.day}"


def _bucket_label(moment: datetime, grain: DashboardGrain) -> str:
    local = moment.astimezone(SHOP)
    if grain == "hour":
        hour = local.hour % 12 or 12
        return f"{hour} {'AM' if local.hour < 12 else 'PM'}"
    if grain == "month":
        return f"{local:%b}"
    return _day_label(local)


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _day(moment: datetime) -> datetime:
    local = moment.astimezone(SHOP)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _day_on(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=SHOP)


def _shift_days(moment: datetime, days: int) -> datetime:
    return moment + timedelta(days=days)


def _month_start(moment: datetime, offset: int) -> datetime:
    local = moment.astimezone(SHOP)
    month_index = local.year * 12 + (local.month - 1) + offset
    year, month = divmod(month_index, 12)
    return local.replace(
        year=year, month=month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
    )


def _align(moment: datetime, grain: DashboardGrain) -> datetime:
    local = moment.astimezone(SHOP)
    if grain == "hour":
        return local.replace(minute=0, second=0, microsecond=0)
    if grain == "month":
        return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return _day(local)


def _step(moment: datetime, grain: DashboardGrain) -> datetime:
    if grain == "hour":
        return moment + timedelta(hours=1)
    if grain == "week":
        return moment + timedelta(days=7)
    if grain == "month":
        return _month_start(moment, 1)
    return moment + timedelta(days=1)


def _shift(moment: datetime, index: int, grain: DashboardGrain) -> datetime:
    if grain == "hour":
        return moment + timedelta(hours=index)
    if grain == "week":
        return moment + timedelta(days=7 * index)
    if grain == "month":
        return _month_start(moment, index)
    return moment + timedelta(days=index)


def _next_hour(moment: datetime) -> datetime:
    return _align(moment, "hour") + timedelta(hours=1)
