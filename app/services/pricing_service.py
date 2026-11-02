"""The one place prices and discounts are worked out.

Every price the shop charges (product page data, cart, quote, order) goes through `price_line`.
Money is whole taka. Percentages are `Decimal` with two places; the database keeps them as
integers in hundredths of a percent (2800 = 28.00 %). Rounding is ROUND_HALF_UP to whole taka.

For quantity `q`:
  total %  = min(base % + extra %(q), max discount %, 99.99 %)
  unit     = selling price - round(regular x (total % - base %) / 100)
The quantity-1 selling price (`products.price`) is the anchor, so a product's stored price
never moves; only the extra quantity discount is taken off it, worked out on the regular price.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing import PricingSettings
from app.schemas.pricing import (
    PricingSettingsRead,
    PricingSettingsUpdate,
    ProductPricing,
    QuantityTier,
)

HUNDRED = Decimal(100)
CENT = Decimal("0.01")
CEILING = Decimal("99.99")  # A discount never reaches 100 %.
DEFAULT_MAX = Decimal("90")
DEFAULT_TIERS: tuple[tuple[int, str], ...] = (
    (2, "0.25"),
    (3, "0.5"),
    (4, "0.75"),
    (5, "1"),
    (6, "1.25"),
    (7, "1.5"),
    (8, "2"),
)
_ROW_ID = 1


@dataclass(frozen=True)
class Rules:
    """Store-wide settings: the global tiers (empty when switched off) and the cap."""

    tiers: tuple[QuantityTier, ...]
    max_percent: Decimal
    tiers_enabled: bool = True
    saved_tiers: tuple[QuantityTier, ...] = ()


@dataclass(frozen=True)
class Line:
    regular_price: int
    base_percent: Decimal
    quantity_percent: Decimal
    total_percent: Decimal
    unit_price: int
    quantity: int
    line_total: int


def percent(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def taka(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_hundredths(value: Decimal) -> int:
    return int(percent(value) * HUNDRED)


def from_hundredths(value: int) -> Decimal:
    return percent(Decimal(value) / HUNDRED)


def selling_price(regular: int, base_percent: Decimal) -> int:
    """Quantity-1 price: the regular price less the base discount."""
    return max(taka(Decimal(regular) * (HUNDRED - percent(base_percent)) / HUNDRED), 0)


def base_percent_of(regular: int, price: int, stored: int | None) -> Decimal:
    """The admin's base % when saved; otherwise derived from regular and selling price."""
    if stored is not None:
        return from_hundredths(stored)
    if regular <= 0 or price >= regular:
        return Decimal("0.00")
    return percent(Decimal(regular - price) * HUNDRED / Decimal(regular))


def extra_for(quantity: int, tiers: tuple[QuantityTier, ...] | list[QuantityTier]) -> Decimal:
    """Extra % of the highest tier reached (tiers need not be sorted)."""
    best = Decimal("0.00")
    reached = 0
    for tier in tiers:
        if tier.min_quantity <= quantity and tier.min_quantity > reached:
            reached = tier.min_quantity
            best = percent(tier.extra_percent)
    return best


def cap_of(rules: Rules) -> Decimal:
    return min(percent(rules.max_percent), CEILING)


def price_line(
    *,
    regular: int,
    price: int,
    stored_base: int | None,
    quantity: int,
    tiers: tuple[QuantityTier, ...] | list[QuantityTier],
    rules: Rules,
) -> Line:
    """Price `quantity` units. `regular`/`price` are the row's regular and selling price."""
    regular = max(regular, price)
    base = base_percent_of(regular, price, stored_base)
    cap = cap_of(rules)
    total = min(base + extra_for(quantity, tiers), cap)
    if total >= base:
        unit = price - taka(Decimal(regular) * (total - base) / HUNDRED)
    else:
        # The cap was lowered below this product's base discount: the cap wins.
        unit = selling_price(regular, total)
    unit = max(unit, 0)
    return Line(
        regular_price=regular,
        base_percent=base,
        quantity_percent=max(total - base, Decimal("0.00")),
        total_percent=total,
        unit_price=unit,
        quantity=quantity,
        line_total=unit * quantity,
    )


def tiers_from_json(raw: list[Any] | None) -> tuple[QuantityTier, ...]:
    tiers: list[QuantityTier] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        try:
            tiers.append(
                QuantityTier(
                    min_quantity=int(item["min_quantity"]),
                    extra_percent=from_hundredths(int(item["extra"])),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(sorted(tiers, key=lambda tier: tier.min_quantity))


def tiers_to_json(tiers: list[QuantityTier] | tuple[QuantityTier, ...]) -> list[dict[str, int]]:
    return [
        {"min_quantity": tier.min_quantity, "extra": to_hundredths(tier.extra_percent)}
        for tier in sorted(tiers, key=lambda tier: tier.min_quantity)
    ]


def default_tiers() -> tuple[QuantityTier, ...]:
    return tuple(
        QuantityTier(min_quantity=quantity, extra_percent=Decimal(extra))
        for quantity, extra in DEFAULT_TIERS
    )


def _rules(row: PricingSettings | None) -> Rules:
    if row is None:
        tiers = default_tiers()
        return Rules(tiers=tiers, max_percent=DEFAULT_MAX, tiers_enabled=True, saved_tiers=tiers)
    saved = tiers_from_json(row.tiers)
    return Rules(
        tiers=saved if row.tiers_enabled else (),
        max_percent=from_hundredths(row.max_discount),
        tiers_enabled=row.tiers_enabled,
        saved_tiers=saved,
    )


async def store_rules(db: AsyncSession) -> Rules:
    return _rules(await db.get(PricingSettings, _ROW_ID))


def product_tiers(product: Any, rules: Rules) -> tuple[QuantityTier, ...]:
    """The tiers a product follows: its own when set to custom, else the global ones."""
    if getattr(product, "tier_mode", "global") == "custom":
        return tiers_from_json(product.tiers)
    return rules.tiers


def regular_of(price: int, compare_at_price: int | None) -> int:
    return compare_at_price if compare_at_price is not None and compare_at_price > price else price


def price_product(product: Any, variant: Any | None, quantity: int, rules: Rules) -> Line:
    """Price a product (or one of its variants) for `quantity` units."""
    row = variant if variant is not None else product
    stored = None if variant is not None else product.base_discount
    return price_line(
        regular=regular_of(row.price, row.compare_at_price),
        price=row.price,
        stored_base=stored,
        quantity=quantity,
        tiers=product_tiers(product, rules),
        rules=rules,
    )


def product_pricing(product: Any, rules: Rules, variant: Any | None = None) -> ProductPricing:
    """Quantity-1 price, base %, cap and tiers: enough to show the price for any quantity."""
    line = price_product(product, variant, 1, rules)
    return ProductPricing(
        regular_price=line.regular_price,
        selling_price=line.unit_price,
        base_discount_percent=line.base_percent,
        max_discount_percent=cap_of(rules),
        tiers=list(product_tiers(product, rules)),
    )


def read_settings(rules: Rules) -> PricingSettingsRead:
    return PricingSettingsRead(
        tiers_enabled=rules.tiers_enabled,
        max_discount_percent=percent(rules.max_percent),
        tiers=list(rules.saved_tiers),
    )


async def get_settings(db: AsyncSession) -> PricingSettingsRead:
    return read_settings(await store_rules(db))


async def set_settings(db: AsyncSession, payload: PricingSettingsUpdate) -> PricingSettingsRead:
    row = await db.get(PricingSettings, _ROW_ID)
    if row is None:
        row = PricingSettings(id=_ROW_ID, tiers_enabled=True, max_discount=0, tiers=[])
        db.add(row)
    row.tiers_enabled = payload.tiers_enabled
    row.max_discount = to_hundredths(payload.max_discount_percent)
    row.tiers = tiers_to_json(payload.tiers)
    await db.commit()
    await db.refresh(row)
    return read_settings(_rules(row))
