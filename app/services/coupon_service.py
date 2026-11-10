"""Coupon rules for the quote, the order, and the admin screens.

The shopper sends only a code. The discount, the free-delivery flag, and the
new total are computed here. A quote reports a bad code and still returns
prices. Placing an order re-checks the same rules inside the order transaction
with the coupon row locked, and rejects the order when the code is no longer
valid.

Cancelling an order marks its redemption cancelled, so the use comes back.
Returning an order leaves the redemption counted: the discount was already
given and the sale stays on the delivery day.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, CouponError, NotFoundError, UnprocessableError
from app.models.category import Category
from app.models.coupon import Coupon, CouponCategory, CouponProduct, CouponRedemption
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.user import User
from app.schemas.coupon import (
    CouponList,
    CouponQuery,
    CouponRead,
    CouponRedemptionList,
    CouponRedemptionRead,
    CouponStatus,
    CouponUpdate,
    CouponWrite,
    check_coupon_shape,
    coupon_page_count,
)
from app.schemas.inquiry import normalize_phone
from app.schemas.order import CouponQuoteRead, QuoteLineRead
from app.services import pricing_service
from app.services.category_service import load_index
from app.services.shop_sql import dialect_name

_BN = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
_CODE = re.compile(r"^[A-Z0-9_-]{3,32}$")

NOT_FOUND = (
    "coupon_not_found",
    "এই কুপন কোডটি পাওয়া যায়নি। বানানটা আবার দেখুন।",
)
INACTIVE = ("coupon_inactive", "এই কুপনটি এখন বন্ধ আছে।")
NOT_STARTED = ("coupon_not_started", "এই কুপনটি এখনো চালু হয়নি।")
EXPIRED = ("coupon_expired", "এই কুপনের মেয়াদ শেষ হয়ে গেছে।")
USAGE_LIMIT = (
    "coupon_usage_limit",
    "এই কুপনটি ব্যবহারের সর্বোচ্চ সীমায় পৌঁছে গেছে।",
)
PHONE_LIMIT = (
    "coupon_phone_limit",
    "এই মোবাইল নম্বরে এই কুপনটি আর ব্যবহার করা যাবে না।",
)
FIRST_ORDER = (
    "coupon_first_order_only",
    "এই কুপনটি শুধু আপনার প্রথম অর্ডারে ব্যবহার করা যাবে।",
)
NOT_ELIGIBLE = (
    "coupon_not_eligible",
    "আপনার কার্টে এই কুপনের জন্য কোনো পণ্য নেই।",
)


@dataclass(frozen=True)
class MoneyLine:
    product_id: uuid.UUID
    category_id: uuid.UUID | None
    line_total: int


@dataclass(frozen=True)
class PricedCoupon:
    coupon_id: uuid.UUID
    code: str
    discount: int
    free_delivery: bool


@dataclass(frozen=True)
class _Failure:
    error_code: str
    message: str


def _taka(amount: int) -> str:
    return f"৳{amount:,}".translate(_BN)


def _min_message(amount: int) -> _Failure:
    return _Failure(
        "coupon_min_amount",
        f"এই কুপনটি কমপক্ষে {_taka(amount)}-এর অর্ডারে ব্যবহার করা যাবে।",
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    return _aware(current) or datetime.now(UTC)


def parse_code(raw: str | None) -> tuple[str | None, bool]:
    """(normalized code or None, whether the shopper sent something).

    A blank value is "no coupon". Anything else is an attempt. A shape that
    is not a code does not match a row, so it is "not found".
    """
    if raw is None:
        return None, False
    text = raw.strip()
    if not text:
        return None, False
    code = text.upper()
    if not _CODE.fullmatch(code):
        return None, True
    return code, True


def shown_code(raw: str) -> str:
    return raw.strip().upper()[:32]


def status_of(coupon: Coupon, now: datetime) -> CouponStatus:
    if not coupon.is_active:
        return "inactive"
    start = _aware(coupon.starts_at)
    end = _aware(coupon.ends_at)
    if start is not None and now < start:
        return "scheduled"
    if end is not None and now > end:
        return "expired"
    return "active"


def discount_amount(coupon: Coupon, eligible: int) -> int:
    """Taka off the eligible merchandise. Never more than that merchandise.

    A percent uses the same round-up-the-payable rule as a quantity discount,
    then the optional cap. A fixed amount is whole taka, also capped by the
    eligible subtotal.
    """
    if eligible <= 0:
        return 0
    if coupon.discount_type == "percent":
        percent = Decimal(coupon.value)
        payable = pricing_service.discounted_total(eligible, percent)
        amount = eligible - payable
        if coupon.max_discount is not None:
            amount = min(amount, int(coupon.max_discount))
    else:
        amount = min(int(Decimal(coupon.value)), eligible)
    return max(0, min(amount, eligible))


async def _categories_for(
    db: AsyncSession, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID | None]:
    if not product_ids:
        return {}
    rows = (
        await db.execute(
            select(Product.id, Product.category_id).where(Product.id.in_(product_ids))
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def lines_from_quote(db: AsyncSession, lines: list[QuoteLineRead]) -> list[MoneyLine]:
    available = [line for line in lines if line.available]
    categories = await _categories_for(db, [line.product_id for line in available])
    return [
        MoneyLine(line.product_id, categories.get(line.product_id), line.line_total)
        for line in available
    ]


def _like(term: str) -> str:
    escaped = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _restrictions(
    db: AsyncSession, coupon_id: uuid.UUID
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    products = set(
        (
            await db.scalars(
                select(CouponProduct.product_id).where(CouponProduct.coupon_id == coupon_id)
            )
        ).all()
    )
    listed = set(
        (
            await db.scalars(
                select(CouponCategory.category_id).where(CouponCategory.coupon_id == coupon_id)
            )
        ).all()
    )
    if not listed:
        return products, set()
    index = await load_index(db)
    expanded: set[uuid.UUID] = set()
    for category_id in listed:
        expanded.update(index.descendants(category_id))
    return products, expanded


def _eligible(lines: list[MoneyLine], products: set[uuid.UUID], categories: set[uuid.UUID]) -> int:
    restricted = bool(products or categories)
    if not restricted:
        return sum(line.line_total for line in lines)
    total = 0
    for line in lines:
        in_category = line.category_id is not None and line.category_id in categories
        if line.product_id in products or in_category:
            total += line.line_total
    return total


async def _active_uses(
    db: AsyncSession, coupon_id: uuid.UUID, phone: str | None = None
) -> int:
    stmt = (
        select(func.count())
        .select_from(CouponRedemption)
        .where(
            CouponRedemption.coupon_id == coupon_id,
            CouponRedemption.cancelled_at.is_(None),
        )
    )
    if phone is not None:
        stmt = stmt.where(CouponRedemption.phone == phone)
    return int((await db.execute(stmt)).scalar_one())


async def _lock_phone(db: AsyncSession, phone: str) -> None:
    """One first-order check at a time for this phone, on PostgreSQL."""
    if dialect_name(db) != "postgresql":
        return
    from sqlalchemy import text

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:phone))"),
        {"phone": phone},
    )


async def _has_prior_order(db: AsyncSession, phone: str) -> bool:
    """True when this phone already has an order that was not cancelled.

    Delivered, returned, and still-open orders all count. A cancelled order
    does not, so the phone can use a first-order coupon after a cancellation.
    """
    await _lock_phone(db, phone)
    stmt = (
        select(Order.id)
        .where(Order.phone == phone, Order.status != OrderStatus.CANCELLED.value)
        .limit(1)
    )
    if dialect_name(db) == "postgresql":
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).first() is not None


async def _load_coupon(db: AsyncSession, code: str, *, lock: bool) -> Coupon | None:
    stmt = select(Coupon).where(func.lower(Coupon.code) == code.lower())
    if lock and dialect_name(db) == "postgresql":
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _judge(
    db: AsyncSession,
    coupon: Coupon,
    lines: list[MoneyLine],
    *,
    phone: str | None,
    now: datetime,
) -> PricedCoupon | _Failure:
    start = _aware(coupon.starts_at)
    end = _aware(coupon.ends_at)
    if not coupon.is_active:
        return _Failure(*INACTIVE)
    if start is not None and now < start:
        return _Failure(*NOT_STARTED)
    if end is not None and now > end:
        return _Failure(*EXPIRED)
    subtotal = sum(line.line_total for line in lines)
    if coupon.min_order_amount is not None and subtotal < coupon.min_order_amount:
        return _min_message(int(coupon.min_order_amount))
    used = await _active_uses(db, coupon.id)
    if coupon.usage_limit_total is not None and used >= coupon.usage_limit_total:
        return _Failure(*USAGE_LIMIT)
    if phone is not None and coupon.usage_limit_per_phone is not None:
        by_phone = await _active_uses(db, coupon.id, phone)
        if by_phone >= coupon.usage_limit_per_phone:
            return _Failure(*PHONE_LIMIT)
    if phone is not None and coupon.first_order_only and await _has_prior_order(db, phone):
        return _Failure(*FIRST_ORDER)
    products, categories = await _restrictions(db, coupon.id)
    restricted = bool(products or categories)
    eligible = _eligible(lines, products, categories)
    if restricted and eligible <= 0:
        return _Failure(*NOT_ELIGIBLE)
    return PricedCoupon(
        coupon_id=coupon.id,
        code=coupon.code,
        discount=discount_amount(coupon, eligible),
        free_delivery=bool(coupon.free_delivery),
    )


def _quote_failure(code: str, failure: _Failure) -> CouponQuoteRead:
    return CouponQuoteRead(
        code=code,
        valid=False,
        discount=0,
        free_delivery=False,
        error_code=failure.error_code,
        message=failure.message,
    )


async def preview(
    db: AsyncSession,
    raw_code: str | None,
    lines: list[QuoteLineRead],
    *,
    phone: str | None = None,
    now: datetime | None = None,
) -> CouponQuoteRead | None:
    """None when no code was sent. A bad code is reported and does not raise."""
    normalized, attempted = parse_code(raw_code)
    if not attempted or raw_code is None:
        return None
    shown = shown_code(raw_code)
    if normalized is None:
        return _quote_failure(shown, _Failure(*NOT_FOUND))
    coupon = await _load_coupon(db, normalized, lock=False)
    if coupon is None:
        return _quote_failure(shown, _Failure(*NOT_FOUND))
    money = await lines_from_quote(db, lines)
    resolved = normalize_phone(phone) if phone else None
    outcome = await _judge(db, coupon, money, phone=resolved, now=_now(now))
    if isinstance(outcome, _Failure):
        return _quote_failure(coupon.code, outcome)
    return CouponQuoteRead(
        code=outcome.code,
        valid=True,
        discount=outcome.discount,
        free_delivery=outcome.free_delivery,
    )


async def lock_and_price(
    db: AsyncSession,
    raw_code: str,
    lines: list[MoneyLine],
    phone: str,
    *,
    now: datetime | None = None,
) -> PricedCoupon:
    """Lock the coupon and price it. Raises CouponError when it cannot be used.

    The caller inserts the redemption in the same transaction, after the order
    row exists. The lock is held until that transaction commits.
    """
    normalized, attempted = parse_code(raw_code)
    shown = shown_code(raw_code)
    if not attempted or normalized is None:
        failure = _Failure(*NOT_FOUND)
        raise CouponError(failure.error_code, failure.message)
    coupon = await _load_coupon(db, normalized, lock=True)
    if coupon is None:
        failure = _Failure(*NOT_FOUND)
        raise CouponError(failure.error_code, failure.message)
    outcome = await _judge(db, coupon, lines, phone=phone, now=_now(now))
    if isinstance(outcome, _Failure):
        raise CouponError(outcome.error_code, outcome.message)
    del shown
    return outcome


def stage_redemption(
    db: AsyncSession, priced: PricedCoupon, order_id: uuid.UUID, phone: str
) -> None:
    db.add(
        CouponRedemption(
            coupon_id=priced.coupon_id,
            order_id=order_id,
            phone=phone,
            discount_amount=priced.discount,
            status="active",
            created_at=datetime.now(UTC),
        )
    )


async def cancel_for_order(db: AsyncSession, order_id: uuid.UUID) -> None:
    """Stop counting this order's coupon. A missing redemption is fine."""
    await db.execute(
        update(CouponRedemption)
        .where(
            CouponRedemption.order_id == order_id,
            CouponRedemption.cancelled_at.is_(None),
        )
        .values(status="cancelled", cancelled_at=datetime.now(UTC))
    )


async def _used_counts(db: AsyncSession, coupon_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not coupon_ids:
        return {}
    rows = (
        await db.execute(
            select(CouponRedemption.coupon_id, func.count())
            .where(
                CouponRedemption.coupon_id.in_(coupon_ids),
                CouponRedemption.cancelled_at.is_(None),
            )
            .group_by(CouponRedemption.coupon_id)
        )
    ).all()
    return {row[0]: int(row[1]) for row in rows}


async def _link_ids(
    db: AsyncSession, coupon_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[uuid.UUID]], dict[uuid.UUID, list[uuid.UUID]]]:
    products: dict[uuid.UUID, list[uuid.UUID]] = {coupon_id: [] for coupon_id in coupon_ids}
    categories: dict[uuid.UUID, list[uuid.UUID]] = {coupon_id: [] for coupon_id in coupon_ids}
    if not coupon_ids:
        return products, categories
    for coupon_id, product_id in (
        await db.execute(
            select(CouponProduct.coupon_id, CouponProduct.product_id)
            .where(CouponProduct.coupon_id.in_(coupon_ids))
            .order_by(CouponProduct.product_id)
        )
    ).all():
        products[coupon_id].append(product_id)
    for coupon_id, category_id in (
        await db.execute(
            select(CouponCategory.coupon_id, CouponCategory.category_id)
            .where(CouponCategory.coupon_id.in_(coupon_ids))
            .order_by(CouponCategory.category_id)
        )
    ).all():
        categories[coupon_id].append(category_id)
    return products, categories


def _read(
    coupon: Coupon,
    *,
    products: list[uuid.UUID],
    categories: list[uuid.UUID],
    used: int,
    now: datetime,
) -> CouponRead:
    return CouponRead(
        id=coupon.id,
        code=coupon.code,
        discount_type=coupon.discount_type,
        value=Decimal(coupon.value),
        max_discount=coupon.max_discount,
        min_order_amount=coupon.min_order_amount,
        starts_at=_aware(coupon.starts_at),
        ends_at=_aware(coupon.ends_at),
        usage_limit_total=coupon.usage_limit_total,
        usage_limit_per_phone=coupon.usage_limit_per_phone,
        first_order_only=coupon.first_order_only,
        product_ids=products,
        category_ids=categories,
        free_delivery=coupon.free_delivery,
        is_active=coupon.is_active,
        status=status_of(coupon, now),
        used_count=used,
        created_by=coupon.created_by,
        created_at=_aware(coupon.created_at) or datetime.now(UTC),
        updated_at=_aware(coupon.updated_at) or datetime.now(UTC),
    )


async def _reads(db: AsyncSession, coupons: list[Coupon], now: datetime) -> list[CouponRead]:
    ids = [coupon.id for coupon in coupons]
    used = await _used_counts(db, ids)
    products, categories = await _link_ids(db, ids)
    return [
        _read(
            coupon,
            products=products.get(coupon.id, []),
            categories=categories.get(coupon.id, []),
            used=used.get(coupon.id, 0),
            now=now,
        )
        for coupon in coupons
    ]


async def _one(db: AsyncSession, coupon_id: uuid.UUID) -> Coupon:
    coupon = await db.get(Coupon, coupon_id)
    if coupon is None:
        raise NotFoundError("Coupon not found")
    return coupon


def _status_filter(status: CouponStatus, now: datetime) -> Any:
    started = or_(Coupon.starts_at.is_(None), Coupon.starts_at <= now)
    not_ended = or_(Coupon.ends_at.is_(None), Coupon.ends_at >= now)
    if status == "inactive":
        return Coupon.is_active.is_(False)
    if status == "scheduled":
        return (Coupon.is_active.is_(True), Coupon.starts_at.is_not(None), Coupon.starts_at > now)
    if status == "expired":
        return (
            Coupon.is_active.is_(True),
            Coupon.ends_at.is_not(None),
            Coupon.ends_at < now,
            started,
        )
    return (Coupon.is_active.is_(True), started, not_ended)


async def list_coupons(db: AsyncSession, query: CouponQuery) -> CouponList:
    now = _now(None)
    stmt = select(Coupon)
    count = select(func.count()).select_from(Coupon)
    if query.q:
        pattern = _like(query.q)
        match = func.lower(Coupon.code).like(pattern, escape="\\")
        stmt = stmt.where(match)
        count = count.where(match)
    if query.status is not None:
        filt = _status_filter(query.status, now)
        conditions = filt if isinstance(filt, tuple) else (filt,)
        for condition in conditions:
            stmt = stmt.where(condition)
            count = count.where(condition)
    total = int((await db.execute(count)).scalar_one())
    rows = list(
        (
            await db.scalars(
                stmt.order_by(Coupon.created_at.desc(), Coupon.id.desc())
                .offset(query.offset)
                .limit(query.page_size)
            )
        ).all()
    )
    return CouponList(
        items=await _reads(db, rows, now),
        total=total,
        page=query.page,
        page_size=query.page_size,
        pages=coupon_page_count(total, query.page_size),
    )


async def get_coupon(db: AsyncSession, coupon_id: uuid.UUID) -> CouponRead:
    coupon = await _one(db, coupon_id)
    return (await _reads(db, [coupon], _now(None)))[0]


async def _require_ids(
    db: AsyncSession,
    model: type[Product] | type[Category],
    ids: list[uuid.UUID],
    message: str,
) -> None:
    if not ids:
        return
    found = set((await db.scalars(select(model.id).where(model.id.in_(ids)))).all())
    missing = [str(item) for item in ids if item not in found]
    if missing:
        raise UnprocessableError(message, {"missing_ids": missing})


async def _replace_links(
    db: AsyncSession,
    coupon_id: uuid.UUID,
    product_ids: list[uuid.UUID],
    category_ids: list[uuid.UUID],
) -> None:
    await _require_ids(db, Product, product_ids, "কিছু পণ্য খুঁজে পাওয়া যায়নি।")
    await _require_ids(db, Category, category_ids, "কিছু ক্যাটাগরি খুঁজে পাওয়া যায়নি।")
    await db.execute(delete(CouponProduct).where(CouponProduct.coupon_id == coupon_id))
    await db.execute(delete(CouponCategory).where(CouponCategory.coupon_id == coupon_id))
    for product_id in product_ids:
        db.add(CouponProduct(coupon_id=coupon_id, product_id=product_id))
    for category_id in category_ids:
        db.add(CouponCategory(coupon_id=coupon_id, category_id=category_id))


def _merged_shape(coupon: Coupon, payload: CouponUpdate) -> None:
    sent = payload.model_fields_set
    discount_type = coupon.discount_type
    if "discount_type" in sent and payload.discount_type is not None:
        discount_type = payload.discount_type
    value = Decimal(coupon.value)
    if "value" in sent and payload.value is not None:
        value = payload.value
    max_discount = payload.max_discount if "max_discount" in sent else coupon.max_discount
    free_delivery = coupon.free_delivery
    if "free_delivery" in sent and payload.free_delivery is not None:
        free_delivery = payload.free_delivery
    starts = payload.starts_at if "starts_at" in sent else _aware(coupon.starts_at)
    ends = payload.ends_at if "ends_at" in sent else _aware(coupon.ends_at)
    try:
        check_coupon_shape(
            discount_type=discount_type,
            value=value,
            max_discount=max_discount,
            free_delivery=bool(free_delivery),
            starts_at=starts,
            ends_at=ends,
        )
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc


async def create_coupon(db: AsyncSession, payload: CouponWrite, actor: User) -> CouponRead:
    coupon = Coupon(
        code=payload.code,
        discount_type=payload.discount_type,
        value=payload.value,
        max_discount=payload.max_discount,
        min_order_amount=payload.min_order_amount,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        usage_limit_total=payload.usage_limit_total,
        usage_limit_per_phone=payload.usage_limit_per_phone,
        first_order_only=payload.first_order_only,
        free_delivery=payload.free_delivery,
        is_active=payload.is_active,
        created_by=actor.id,
    )
    db.add(coupon)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("এই কুপন কোডটি আগে থেকেই আছে।") from None
    await _replace_links(db, coupon.id, payload.product_ids, payload.category_ids)
    coupon_id = coupon.id
    await db.commit()
    db.expire_all()
    return await get_coupon(db, coupon_id)


async def update_coupon(
    db: AsyncSession, coupon_id: uuid.UUID, payload: CouponUpdate
) -> CouponRead:
    coupon = await _one(db, coupon_id)
    _merged_shape(coupon, payload)
    sent = payload.model_fields_set
    if "code" in sent and payload.code is not None:
        coupon.code = payload.code
    if "discount_type" in sent and payload.discount_type is not None:
        coupon.discount_type = payload.discount_type
    if "value" in sent and payload.value is not None:
        coupon.value = payload.value
    if "max_discount" in sent:
        coupon.max_discount = payload.max_discount
    if "min_order_amount" in sent:
        coupon.min_order_amount = payload.min_order_amount
    if "starts_at" in sent:
        coupon.starts_at = payload.starts_at
    if "ends_at" in sent:
        coupon.ends_at = payload.ends_at
    if "usage_limit_total" in sent:
        coupon.usage_limit_total = payload.usage_limit_total
    if "usage_limit_per_phone" in sent:
        coupon.usage_limit_per_phone = payload.usage_limit_per_phone
    if "first_order_only" in sent and payload.first_order_only is not None:
        coupon.first_order_only = payload.first_order_only
    if "free_delivery" in sent and payload.free_delivery is not None:
        coupon.free_delivery = payload.free_delivery
    if "is_active" in sent and payload.is_active is not None:
        coupon.is_active = payload.is_active
    if "product_ids" in sent or "category_ids" in sent:
        products, categories = await _link_ids(db, [coupon.id])
        product_ids = payload.product_ids if "product_ids" in sent else products.get(coupon.id, [])
        category_ids = (
            payload.category_ids if "category_ids" in sent else categories.get(coupon.id, [])
        )
        await _replace_links(db, coupon.id, product_ids or [], category_ids or [])
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("এই কুপন কোডটি আগে থেকেই আছে।") from None
    db.expire_all()
    return await get_coupon(db, coupon_id)


async def set_active(db: AsyncSession, coupon_id: uuid.UUID, active: bool) -> CouponRead:
    coupon = await _one(db, coupon_id)
    coupon.is_active = active
    await db.commit()
    db.expire_all()
    return await get_coupon(db, coupon_id)


async def list_redemptions(
    db: AsyncSession, coupon_id: uuid.UUID, *, page: int, page_size: int
) -> CouponRedemptionList:
    await _one(db, coupon_id)
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(CouponRedemption)
                .where(CouponRedemption.coupon_id == coupon_id)
            )
        ).scalar_one()
    )
    offset = (page - 1) * page_size
    rows = (
        await db.execute(
            select(CouponRedemption, Order.number)
            .join(Order, Order.id == CouponRedemption.order_id)
            .where(CouponRedemption.coupon_id == coupon_id)
            .order_by(CouponRedemption.created_at.desc(), CouponRedemption.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).all()
    items: list[CouponRedemptionRead] = []
    for redemption, number in rows:
        items.append(
            CouponRedemptionRead(
                id=redemption.id,
                coupon_id=redemption.coupon_id,
                order_id=redemption.order_id,
                order_number=str(number),
                phone=redemption.phone,
                discount_amount=int(redemption.discount_amount),
                status=redemption.status,
                cancelled_at=_aware(redemption.cancelled_at),
                created_at=_aware(redemption.created_at) or datetime.now(UTC),
            )
        )
    return CouponRedemptionList(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=coupon_page_count(total, page_size),
    )
