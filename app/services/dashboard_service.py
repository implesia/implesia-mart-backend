"""Shop overview for the admin dashboard.

Figures follow the overview page: revenue leaves out cancelled and returned
orders, customers are unique checkout phones, and "today" is compared with the
same hours of yesterday in Asia/Dhaka.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
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

SHOP = ZoneInfo("Asia/Dhaka")
STATUSES = ("new", "confirmed", "shipped", "delivered", "cancelled", "returned")
EXCLUDED = {"cancelled", "returned"}
MAX_DAYS = 366
_GRAIN_LABEL = {"hour": "Hourly", "day": "Daily", "week": "Weekly", "month": "Monthly"}
CATEGORY_LABEL = {"gadgets": "Trending gadgets", "fashion": "Gorgeous dresses"}
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
_DIGITS = re.compile(r"\D+")


@dataclass(frozen=True)
class _Window:
    start: datetime
    end: datetime


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
    orders = await _load(db, previous.start, previous.end, current.start, current.end)
    current_orders = [order for order in orders if _inside(order, current)]
    previous_orders = [order for order in orders if _inside(order, previous)]
    sales = [order for order in current_orders if _sale(order)]
    previous_sales = [order for order in previous_orders if _sale(order)]
    series = _series(orders, current, previous, grain, moment)
    revenue = sum(order.total for order in sales)
    previous_revenue = sum(order.total for order in previous_sales)
    customers = _customers(current_orders)
    previous_customers = _customers(previous_orders)
    pending = sum(order.status == "new" for order in current_orders)
    previous_pending = sum(order.status == "new" for order in previous_orders)
    delivered = sum(order.status == "delivered" for order in current_orders)
    previous_delivered = sum(order.status == "delivered" for order in previous_orders)
    average = _average(revenue, len(sales))
    previous_average = _average(previous_revenue, len(previous_sales))
    return DashboardOverview(
        range=span,
        period_label=_span_label(current),
        comparison_label=f"vs {_span_label(previous)}",
        grain=grain,
        grain_label=_GRAIN_LABEL[grain],
        revenue=_metric(
            revenue, _taka(revenue), previous_revenue, [point.revenue for point in series]
        ),
        orders=_metric(
            len(current_orders),
            str(len(current_orders)),
            len(previous_orders),
            [point.orders for point in series],
        ),
        customers=_metric(customers, str(customers), previous_customers, []),
        average_order=_metric(average, _taka(average), previous_average, []),
        pending=_metric(pending, str(pending), previous_pending, []),
        delivered=_metric(delivered, str(delivered), previous_delivered, []),
        series=series,
        statuses=_statuses(current_orders),
        order_count=len(current_orders),
        best_sellers=_sellers(sales),
        recent=_recent(current_orders),
        areas=_areas(current_orders),
        categories=_categories(sales),
    )


async def _load(
    db: AsyncSession,
    previous_start: datetime,
    previous_end: datetime,
    current_start: datetime,
    current_end: datetime,
) -> list[Order]:
    result = await db.scalars(
        select(Order)
        .where(
            or_(
                (Order.created_at >= previous_start) & (Order.created_at < previous_end),
                (Order.created_at >= current_start) & (Order.created_at < current_end),
            )
        )
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .order_by(Order.created_at.desc())
    )
    return list(result.unique().all())


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


def _series(
    orders: list[Order],
    current: _Window,
    previous: _Window,
    grain: DashboardGrain,
    now: datetime,
) -> list[DashboardPoint]:
    end = current.end
    if grain == "hour" and current.start <= now < current.end:
        end = min(current.end, _next_hour(now))
    buckets = _buckets(current.start, end, grain)
    points: list[DashboardPoint] = []
    for index, bucket in enumerate(buckets):
        duration = bucket.end - bucket.start
        earlier = _shift(previous.start, index, grain)
        points.append(
            DashboardPoint(
                label=_bucket_label(bucket.start, grain),
                revenue=_revenue(orders, bucket),
                orders=sum(_inside(order, bucket) for order in orders),
                previous_revenue=_revenue(orders, _Window(earlier, earlier + duration)),
            )
        )
    return points


def _buckets(start: datetime, end: datetime, grain: DashboardGrain) -> list[_Window]:
    cursor = _align(start, grain)
    buckets: list[_Window] = []
    while cursor < end and len(buckets) < 400:
        nxt = _step(cursor, grain)
        buckets.append(_Window(max(cursor, start), min(nxt, end)))
        cursor = nxt
    return buckets or [_Window(start, end)]


def _sellers(orders: list[Order]) -> list[DashboardSeller]:
    rows: dict[str, DashboardSeller] = {}
    for order in orders:
        for item in order.items:
            product = item.product
            key = str(item.product_id or item.slug)
            current = rows.get(key)
            if current is None:
                image = item.image_src
                if product is not None and product.image_src:
                    image = product.image_src
                current = DashboardSeller(
                    product_id=item.product_id,
                    slug=product.slug if product else item.slug,
                    title=product.title if product else item.title,
                    image_src=image,
                    category=_category_label(product),
                    units=0,
                    revenue=0,
                    stock_label=_stock(product),
                )
            current.units += item.quantity
            current.revenue += item.line_total
            rows[key] = current
    ranked = sorted(rows.values(), key=lambda row: (row.revenue, row.units), reverse=True)
    return ranked[:5]


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


def _areas(orders: list[Order]) -> list[DashboardArea]:
    rows: dict[str, list[int]] = {}
    for order in orders:
        name = _district_name(order.district, order.area, order.address)
        count, revenue = rows.get(name, [0, 0])
        count += 1
        if _sale(order):
            revenue += order.total
        rows[name] = [count, revenue]
    total = len(orders)
    areas = [
        DashboardArea(name=name, orders=count, revenue=revenue, share=_share(count, total))
        for name, (count, revenue) in rows.items()
    ]
    areas.sort(key=lambda row: (row.orders, row.revenue), reverse=True)
    return areas[:6]


def _categories(orders: list[Order]) -> list[DashboardCategory]:
    rows: dict[str, list[int]] = {}
    for order in orders:
        for item in order.items:
            product = item.product
            if product is None or product.category not in CATEGORY_LABEL:
                continue
            units, revenue = rows.get(product.category, [0, 0])
            rows[product.category] = [units + item.quantity, revenue + item.line_total]
    total = sum(revenue for _, revenue in rows.values())
    categories = [
        DashboardCategory(
            id=category,
            label=CATEGORY_LABEL[category],
            revenue=revenue,
            units=units,
            share=_share(revenue, total),
        )
        for category, (units, revenue) in rows.items()
    ]
    categories.sort(key=lambda row: row.revenue, reverse=True)
    return categories


def _statuses(orders: list[Order]) -> list[DashboardStatusSlice]:
    total = len(orders)
    slices: list[DashboardStatusSlice] = []
    for status in STATUSES:
        count = sum(order.status == status for order in orders)
        slices.append(DashboardStatusSlice(status=status, count=count, share=_share(count, total)))
    return slices


def _revenue(orders: list[Order], window: _Window) -> int:
    return sum(order.total for order in orders if _inside(order, window) and _sale(order))


def _customers(orders: list[Order]) -> int:
    seen: set[str] = set()
    for order in orders:
        digits = _DIGITS.sub("", order.phone)
        seen.add(digits[-11:] if len(digits) >= 11 else order.customer_name.strip().casefold())
    return len(seen)


def _sale(order: Order) -> bool:
    return order.status not in EXCLUDED


def _inside(order: Order, window: _Window) -> bool:
    created = _aware(order.created_at)
    return window.start <= created < window.end


def _items_label(order: Order) -> str:
    if not order.items:
        return "—"
    extra = len(order.items) - 1
    title = order.items[0].title
    return f"{title} +{extra}" if extra else title


def _stock(product: Product | None) -> str:
    if product is None or product.status == "available":
        if product is not None and product.quantity is not None:
            return f"{product.quantity} in stock"
        return "In stock"
    if product.status == "sold-out":
        return "Sold out"
    return "Coming soon"


def _category_label(product: Product | None) -> str:
    if product is None:
        return "Uncategorized"
    return CATEGORY_LABEL.get(product.category, "Uncategorized")


def _district_name(district: str, area: str, address: str) -> str:
    for name, keys in DISTRICTS:
        folded = {key.casefold() for key in keys}
        if district.strip().casefold() in folded or area.strip().casefold() in folded:
            return name
    haystack = f"{district} {area} {address}".casefold()
    found: tuple[str, int] | None = None
    for name, keys in DISTRICTS:
        for key in keys:
            index = haystack.rfind(key.casefold())
            if index >= 0 and (found is None or index >= found[1]):
                found = (name, index)
    if found:
        return found[0]
    return district.strip() or area.strip() or "Unknown area"


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
