import math
import re
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import DeliverySettings
from app.schemas.delivery import (
    DEFAULT_SUBURBAN_PLACES,
    DeliveryRatesRead,
    DeliveryRatesUpdate,
)

DEFAULT_INSIDE = 70
DEFAULT_SUBURBAN = 100
DEFAULT_OUTSIDE = 130
DEFAULT_WEIGHT_PRICING_ENABLED = True
DEFAULT_BASE_WEIGHT_GRAMS = 1000
DEFAULT_EXTRA_WEIGHT_STEP_GRAMS = 1000
DEFAULT_EXTRA_FEE_INSIDE = 20
DEFAULT_EXTRA_FEE_SUBURBAN = 20
DEFAULT_EXTRA_FEE_OUTSIDE = 20
DEFAULT_PACKAGING_WEIGHT_GRAMS = 0
DEFAULT_PRODUCT_WEIGHT_GRAMS = 500
_ROW_ID = 1
_RANK = {"inside": 0, "suburban": 1, "outside": 2}
_DHAKA = {"dhaka", "ঢাকা", "dhaka city", "dhaka district", "ঢাকা জেলা", "ঢাকা শহর"}
# Known Bangla / common spelling aliases for canonical suburban places.
# Only activated when the corresponding place is present in `suburban_places`.
_PLACE_ALIASES: dict[str, tuple[str, ...]] = {
    "savar": (
        "savar",
        "shavar",
        "sabhar",
        "saver",
        "সাভার",
        "শাভার",
        "hemayetpur",
        "হেমায়েতপুর",
        "হেমায়েতপুর",
        "aminbazar",
        "আমিনবাজার",
        "nabinagar",
        "নবীনগর",
        "baipail",
        "বাইপাইল",
        "birulia",
        "বিরুলিয়া",
        "বিরুলিয়া",
        "depz",
        "ডিইপিজেড",
    ),
    "ashulia": (
        "ashulia",
        "ashuliya",
        "asulia",
        "asukiya",
        "আশুলিয়া",
        "আশুলিয়া",
        "zirabo",
        "jirabo",
        "জিরাবো",
    ),
    "gazipur": (
        "gazipur",
        "gajipur",
        "গাজীপুর",
        "গাজিপুর",
        "tongi",
        "টঙ্গী",
        "টঙ্গি",
        "joydebpur",
        "জয়দেবপুর",
        "জয়দেবপুর",
        "konabari",
        "কোনাবাড়ী",
        "কোনাবাড়ি",
        "kaliakair",
        "কালিয়াকৈর",
        "sreepur",
        "শ্রীপুর",
        "kapasia",
        "কাপাসিয়া",
    ),
    "keraniganj": (
        "keraniganj",
        "keranigonj",
        "keranigang",
        "কেরানীগঞ্জ",
        "কেরানিগঞ্জ",
        "jinjira",
        "zinzira",
        "জিনজিরা",
        "hasnabad",
        "হাসনাবাদ",
        "kalindi",
        "কালিন্দী",
        "কালিন্দি",
        "teghoria",
        "তেঘরিয়া",
        "তেঘরিয়া",
        "ruhitpur",
        "রুহিতপুর",
    ),
    "narayanganj": (
        "narayanganj",
        "narayangonj",
        "narayanjang",
        "নারায়ণগঞ্জ",
        "নারায়ণগঞ্জ",
        "নারায়নগঞ্জ",
        "fatullah",
        "ফতুল্লা",
        "siddhirganj",
        "সিদ্ধিরগঞ্জ",
        "rupganj",
        "রূপগঞ্জ",
        "sonargaon",
        "সোনারগাঁও",
        "bandar",
        "বন্দর",
    ),
    "dhamrai": ("dhamrai", "dhamray", "ধামরাই"),
    "dohar": ("dohar", "dohor", "দোহার"),
    "nawabganj": ("nawabganj", "নবাবগঞ্জ"),
    "munshiganj": ("munshiganj", "munshigonj", "মুন্সীগঞ্জ", "মুন্সিগঞ্জ"),
    "manikganj": ("manikganj", "manikgonj", "মানিকগঞ্জ"),
    "narsingdi": ("narsingdi", "নরসিংদী", "নরসিংদি"),
    "tongi": ("tongi", "টঙ্গী", "টঙ্গি"),
}
_SPLIT = re.compile(r"[\s,;/|+.\-–—]+")


def _expand_markers(places: tuple[str, ...]) -> tuple[str, ...]:
    markers: list[str] = []
    seen: set[str] = set()
    for raw in places:
        key = " ".join(raw.split()).strip().casefold()
        if not key:
            continue
        for candidate in (key, *_PLACE_ALIASES.get(key, ())):
            if candidate not in seen:
                seen.add(candidate)
                markers.append(candidate)
    return tuple(markers)


def _resolved_suburban_places(raw: list[str] | None) -> list[str]:
    if raw is None:
        return list(DEFAULT_SUBURBAN_PLACES)
    return [str(item).strip() for item in raw if isinstance(item, str) and item.strip()]


class StoreFees(NamedTuple):
    inside: int
    suburban: int
    outside: int
    inside_on: bool = True
    suburban_on: bool = True
    outside_on: bool = True
    weight_pricing_enabled: bool = DEFAULT_WEIGHT_PRICING_ENABLED
    base_weight_grams: int = DEFAULT_BASE_WEIGHT_GRAMS
    extra_weight_step_grams: int = DEFAULT_EXTRA_WEIGHT_STEP_GRAMS
    extra_fee_inside: int = DEFAULT_EXTRA_FEE_INSIDE
    extra_fee_suburban: int = DEFAULT_EXTRA_FEE_SUBURBAN
    extra_fee_outside: int = DEFAULT_EXTRA_FEE_OUTSIDE
    packaging_weight_grams: int = DEFAULT_PACKAGING_WEIGHT_GRAMS
    default_product_weight_grams: int = DEFAULT_PRODUCT_WEIGHT_GRAMS
    suburban_places: tuple[str, ...] = DEFAULT_SUBURBAN_PLACES

    def for_zone(self, zone: str) -> int:
        if zone == "inside":
            return self.inside
        if zone == "suburban":
            return self.suburban
        return self.outside

    def extra_fee_for_zone(self, zone: str) -> int:
        if zone == "inside":
            return self.extra_fee_inside
        if zone == "suburban":
            return self.extra_fee_suburban
        return self.extra_fee_outside

    def enabled(self, zone: str) -> bool:
        if zone == "inside":
            return self.inside_on
        if zone == "suburban":
            return self.suburban_on
        return self.outside_on

    def offered(self) -> list[int]:
        amounts: list[int] = []
        if self.inside_on:
            amounts.append(self.inside)
        if self.suburban_on:
            amounts.append(self.suburban)
        if self.outside_on:
            amounts.append(self.outside)
        return amounts

    def flat(self) -> int | None:
        amounts = self.offered()
        if not amounts:
            return None
        if len(set(amounts)) == 1:
            return amounts[0]
        return None


class ShippingBreakdown(NamedTuple):
    total_fee: int
    base_fee: int
    extra_weight_fee: int
    extra_steps: int
    total_weight_grams: int


def resolve_item_weight_grams(
    product_weight_grams: int | None,
    variant_weight_grams: int | None,
    rates: StoreFees,
) -> int:
    """Variant override > product weight > store default fallback (integer grams)."""
    if variant_weight_grams is not None:
        return max(0, int(variant_weight_grams))
    if product_weight_grams is not None:
        return max(0, int(product_weight_grams))
    return max(0, int(rates.default_product_weight_grams))


def calculate_weight_shipping(
    zone: str,
    total_weight_grams: int,
    rates: StoreFees,
) -> ShippingBreakdown:
    """Bangladesh courier slab formula: base covers up to base_weight_grams;
    each additional started extra_weight_step_grams adds extra_fee_for_zone(zone)."""
    weight = max(0, int(total_weight_grams))
    base_fee = rates.for_zone(zone)
    if not rates.weight_pricing_enabled or weight <= rates.base_weight_grams:
        return ShippingBreakdown(
            total_fee=base_fee,
            base_fee=base_fee,
            extra_weight_fee=0,
            extra_steps=0,
            total_weight_grams=weight,
        )
    step = max(1, int(rates.extra_weight_step_grams))
    extra_steps = math.ceil((weight - rates.base_weight_grams) / step)
    extra_weight_fee = extra_steps * rates.extra_fee_for_zone(zone)
    return ShippingBreakdown(
        total_fee=base_fee + extra_weight_fee,
        base_fee=base_fee,
        extra_weight_fee=extra_weight_fee,
        extra_steps=extra_steps,
        total_weight_grams=weight,
    )


async def _row(db: AsyncSession) -> DeliverySettings | None:
    return await db.get(DeliverySettings, _ROW_ID)


def _read(row: DeliverySettings | None) -> DeliveryRatesRead:
    if row is None:
        return DeliveryRatesRead(
            inside_dhaka=DEFAULT_INSIDE,
            dhaka_suburban=DEFAULT_SUBURBAN,
            outside_dhaka=DEFAULT_OUTSIDE,
            inside_enabled=True,
            suburban_enabled=True,
            outside_enabled=True,
            weight_pricing_enabled=DEFAULT_WEIGHT_PRICING_ENABLED,
            base_weight_grams=DEFAULT_BASE_WEIGHT_GRAMS,
            extra_weight_step_grams=DEFAULT_EXTRA_WEIGHT_STEP_GRAMS,
            extra_fee_inside=DEFAULT_EXTRA_FEE_INSIDE,
            extra_fee_suburban=DEFAULT_EXTRA_FEE_SUBURBAN,
            extra_fee_outside=DEFAULT_EXTRA_FEE_OUTSIDE,
            packaging_weight_grams=DEFAULT_PACKAGING_WEIGHT_GRAMS,
            default_product_weight_grams=DEFAULT_PRODUCT_WEIGHT_GRAMS,
            suburban_places=list(DEFAULT_SUBURBAN_PLACES),
        )
    return DeliveryRatesRead(
        inside_dhaka=row.inside_dhaka,
        dhaka_suburban=row.dhaka_suburban,
        outside_dhaka=row.outside_dhaka,
        inside_enabled=row.inside_enabled,
        suburban_enabled=row.suburban_enabled,
        outside_enabled=row.outside_enabled,
        weight_pricing_enabled=row.weight_pricing_enabled,
        base_weight_grams=row.base_weight_grams,
        extra_weight_step_grams=row.extra_weight_step_grams,
        extra_fee_inside=row.extra_fee_inside,
        extra_fee_suburban=row.extra_fee_suburban,
        extra_fee_outside=row.extra_fee_outside,
        packaging_weight_grams=row.packaging_weight_grams,
        default_product_weight_grams=row.default_product_weight_grams,
        suburban_places=_resolved_suburban_places(row.suburban_places),
    )


async def get_rates(db: AsyncSession) -> DeliveryRatesRead:
    return _read(await _row(db))


async def fees(db: AsyncSession) -> StoreFees:
    row = await _row(db)
    if row is None:
        return StoreFees(DEFAULT_INSIDE, DEFAULT_SUBURBAN, DEFAULT_OUTSIDE)
    return StoreFees(
        row.inside_dhaka,
        row.dhaka_suburban,
        row.outside_dhaka,
        row.inside_enabled,
        row.suburban_enabled,
        row.outside_enabled,
        row.weight_pricing_enabled,
        row.base_weight_grams,
        row.extra_weight_step_grams,
        row.extra_fee_inside,
        row.extra_fee_suburban,
        row.extra_fee_outside,
        row.packaging_weight_grams,
        row.default_product_weight_grams,
        tuple(_resolved_suburban_places(row.suburban_places)),
    )


def _is_dhaka(value: str) -> bool:
    return value.strip().casefold() in _DHAKA


def _place(value: str, markers: tuple[str, ...]) -> bool:
    """True when a marker is the whole place, or the start of a locality such as সাভারবাজার."""
    whole = value.strip().casefold()
    if not whole:
        return False
    parts = [part for part in _SPLIT.split(whole) if part] or [whole]
    for marker in markers:
        if whole == marker or marker in parts:
            return True
        if any(part.startswith(marker) for part in parts):
            return True
    return False


def classify(
    district: str,
    area: str = "",
    suburban_places: tuple[str, ...] | None = None,
) -> str:
    """City centre, a configured Dhaka-suburban district/area, or the rest of the country."""
    district_text = district.strip()
    if not district_text:
        return "outside"
    markers = _expand_markers(
        DEFAULT_SUBURBAN_PLACES if suburban_places is None else suburban_places
    )
    if markers and _place(district_text, markers):
        return "suburban"
    if not _is_dhaka(district_text):
        return "outside"
    if markers and _place(area, markers):
        return "suburban"
    return "inside"


def open_zones(classified: str, rates: StoreFees) -> list[str]:
    """Enabled zones that are not cheaper than the address. Nearest first."""
    floor = _RANK[classified]
    return [zone for zone in _RANK if _RANK[zone] >= floor and rates.enabled(zone)]


def resolve(
    district: str,
    area: str = "",
    declared: str | None = None,
    rates: StoreFees | None = None,
) -> str:
    """A customer can choose a farther open zone. They cannot choose a nearer, cheaper one."""
    classified = classify(
        district, area, rates.suburban_places if rates is not None else None
    )
    if rates is None:
        if declared not in _RANK:
            return classified
        if _RANK[declared] >= _RANK[classified]:
            return declared
        return classified
    choices = open_zones(classified, rates)
    if declared in choices:
        return declared
    if choices:
        return choices[0]
    return classified


def price_for(
    district: str,
    area: str,
    declared: str | None,
    rates: StoreFees,
    total_weight_grams: int = 0,
) -> tuple[str, int, bool]:
    """Zone, fee, and whether that zone is still offered. A closed zone is not a fee of zero."""
    classified = classify(district, area, rates.suburban_places)
    zone = resolve(district, area, declared, rates)
    if not rates.enabled(zone):
        return classified, 0, False
    breakdown = calculate_weight_shipping(zone, total_weight_grams, rates)
    return zone, breakdown.total_fee, True


def breakdown_for(
    district: str,
    area: str,
    declared: str | None,
    rates: StoreFees,
    total_weight_grams: int = 0,
) -> tuple[str, ShippingBreakdown, bool]:
    """Zone, full weight shipping breakdown, and whether that zone is still offered."""
    classified = classify(district, area, rates.suburban_places)
    zone = resolve(district, area, declared, rates)
    if not rates.enabled(zone):
        zero = ShippingBreakdown(
            total_fee=0,
            base_fee=0,
            extra_weight_fee=0,
            extra_steps=0,
            total_weight_grams=max(0, int(total_weight_grams)),
        )
        return classified, zero, False
    return zone, calculate_weight_shipping(zone, total_weight_grams, rates), True


def preview_shipping(
    count: int,
    rates: StoreFees,
    total_weight_grams: int = 0,
) -> int:
    """A cart has no address, so one delivery figure is honest only when every zone matches."""
    if count <= 0:
        return 0
    flat = rates.flat()
    if flat is None:
        return 0
    # When weight pricing is enabled and extra fees also match across enabled zones, include them.
    offered_zones = [zone for zone in ("inside", "suburban", "outside") if rates.enabled(zone)]
    breakdowns = [calculate_weight_shipping(z, total_weight_grams, rates) for z in offered_zones]
    totals = {b.total_fee for b in breakdowns}
    return breakdowns[0].total_fee if len(totals) == 1 else flat


async def set_rates(db: AsyncSession, payload: DeliveryRatesUpdate) -> DeliveryRatesRead:
    row = await _row(db)
    if row is None:
        row = DeliverySettings(
            id=_ROW_ID,
            inside_dhaka=payload.inside_dhaka,
            dhaka_suburban=payload.dhaka_suburban,
            outside_dhaka=payload.outside_dhaka,
            inside_enabled=payload.inside_enabled,
            suburban_enabled=payload.suburban_enabled,
            outside_enabled=payload.outside_enabled,
            weight_pricing_enabled=(
                payload.weight_pricing_enabled
                if payload.weight_pricing_enabled is not None
                else DEFAULT_WEIGHT_PRICING_ENABLED
            ),
            base_weight_grams=(
                payload.base_weight_grams
                if payload.base_weight_grams is not None
                else DEFAULT_BASE_WEIGHT_GRAMS
            ),
            extra_weight_step_grams=(
                payload.extra_weight_step_grams
                if payload.extra_weight_step_grams is not None
                else DEFAULT_EXTRA_WEIGHT_STEP_GRAMS
            ),
            extra_fee_inside=(
                payload.extra_fee_inside
                if payload.extra_fee_inside is not None
                else DEFAULT_EXTRA_FEE_INSIDE
            ),
            extra_fee_suburban=(
                payload.extra_fee_suburban
                if payload.extra_fee_suburban is not None
                else DEFAULT_EXTRA_FEE_SUBURBAN
            ),
            extra_fee_outside=(
                payload.extra_fee_outside
                if payload.extra_fee_outside is not None
                else DEFAULT_EXTRA_FEE_OUTSIDE
            ),
            packaging_weight_grams=(
                payload.packaging_weight_grams
                if payload.packaging_weight_grams is not None
                else DEFAULT_PACKAGING_WEIGHT_GRAMS
            ),
            default_product_weight_grams=(
                payload.default_product_weight_grams
                if payload.default_product_weight_grams is not None
                else DEFAULT_PRODUCT_WEIGHT_GRAMS
            ),
            suburban_places=(
                payload.suburban_places
                if payload.suburban_places is not None
                else list(DEFAULT_SUBURBAN_PLACES)
            ),
        )
        db.add(row)
    else:
        row.inside_dhaka = payload.inside_dhaka
        row.dhaka_suburban = payload.dhaka_suburban
        row.outside_dhaka = payload.outside_dhaka
        row.inside_enabled = payload.inside_enabled
        row.suburban_enabled = payload.suburban_enabled
        row.outside_enabled = payload.outside_enabled
        if payload.weight_pricing_enabled is not None:
            row.weight_pricing_enabled = payload.weight_pricing_enabled
        if payload.base_weight_grams is not None:
            row.base_weight_grams = payload.base_weight_grams
        if payload.extra_weight_step_grams is not None:
            row.extra_weight_step_grams = payload.extra_weight_step_grams
        if payload.extra_fee_inside is not None:
            row.extra_fee_inside = payload.extra_fee_inside
        if payload.extra_fee_suburban is not None:
            row.extra_fee_suburban = payload.extra_fee_suburban
        if payload.extra_fee_outside is not None:
            row.extra_fee_outside = payload.extra_fee_outside
        if payload.packaging_weight_grams is not None:
            row.packaging_weight_grams = payload.packaging_weight_grams
        if payload.default_product_weight_grams is not None:
            row.default_product_weight_grams = payload.default_product_weight_grams
        if payload.suburban_places is not None:
            row.suburban_places = payload.suburban_places
    await db.commit()
    await db.refresh(row)
    return _read(row)
