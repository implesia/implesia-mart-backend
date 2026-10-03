import re
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import DeliverySettings
from app.schemas.delivery import DeliveryRatesRead, DeliveryRatesUpdate

DEFAULT_INSIDE = 70
DEFAULT_SUBURBAN = 100
DEFAULT_OUTSIDE = 130
_ROW_ID = 1
_RANK = {"inside": 0, "suburban": 1, "outside": 2}
_DHAKA = {"dhaka", "ঢাকা", "dhaka city", "dhaka district", "ঢাকা জেলা", "ঢাকা শহর"}
# Dhaka district upazilas and their localities, outside the two city corporations.
# Matched as a whole place name, never as a piece of another district.
_SUBURBAN = (
    "savar",
    "shavar",
    "sabhar",
    "saver",
    "সাভার",
    "শাভার",
    "dhamrai",
    "dhamray",
    "ধামরাই",
    "keraniganj",
    "keranigonj",
    "keranigang",
    "কেরানীগঞ্জ",
    "কেরানিগঞ্জ",
    "dohar",
    "dohor",
    "দোহার",
    "nawabganj",
    "নবাবগঞ্জ",
    "ashulia",
    "আশুলিয়া",
    "আশুলিয়া",
    "hemayetpur",
    "হেমায়েতপুর",
    "হেমায়েতপুর",
    "aminbazar",
    "আমিনবাজার",
    "nabinagar",
    "নবীনগর",
    "baipail",
    "বাইপাইল",
    "zirabo",
    "jirabo",
    "জিরাবো",
    "jinjira",
    "zinzira",
    "জিনজিরা",
    "hasnabad",
    "হাসনাবাদ",
    "birulia",
    "বিরুলিয়া",
    "বিরুলিয়া",
    "kalindi",
    "কালিন্দী",
    "কালিন্দি",
    "teghoria",
    "তেঘরিয়া",
    "তেঘরিয়া",
    "ruhitpur",
    "রুহিতপুর",
    "depz",
    "ডিইপিজেড",
)
_SPLIT = re.compile(r"[\s,;/|+.\-–—]+")


class StoreFees(NamedTuple):
    inside: int
    suburban: int
    outside: int
    inside_on: bool = True
    suburban_on: bool = True
    outside_on: bool = True

    def for_zone(self, zone: str) -> int:
        if zone == "inside":
            return self.inside
        if zone == "suburban":
            return self.suburban
        return self.outside

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
        )
    return DeliveryRatesRead(
        inside_dhaka=row.inside_dhaka,
        dhaka_suburban=row.dhaka_suburban,
        outside_dhaka=row.outside_dhaka,
        inside_enabled=row.inside_enabled,
        suburban_enabled=row.suburban_enabled,
        outside_enabled=row.outside_enabled,
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


def classify(district: str, area: str = "") -> str:
    """City centre, a farther upazila inside Dhaka district, or the rest of the country."""
    district_text = district.strip()
    if not district_text:
        return "outside"
    if _place(district_text, _SUBURBAN):
        return "suburban"
    if not _is_dhaka(district_text):
        return "outside"
    if _place(area, _SUBURBAN):
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
    classified = classify(district, area)
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
    district: str, area: str, declared: str | None, rates: StoreFees
) -> tuple[str, int, bool]:
    """Zone, fee, and whether that zone is still offered. A closed zone is not a fee of zero."""
    classified = classify(district, area)
    zone = resolve(district, area, declared, rates)
    if not rates.enabled(zone):
        return classified, 0, False
    return zone, rates.for_zone(zone), True


def preview_shipping(count: int, rates: StoreFees) -> int:
    """A cart has no address, so one delivery figure is honest only when every zone matches."""
    if count <= 0:
        return 0
    flat = rates.flat()
    return flat if flat is not None else 0


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
        )
        db.add(row)
    else:
        row.inside_dhaka = payload.inside_dhaka
        row.dhaka_suburban = payload.dhaka_suburban
        row.outside_dhaka = payload.outside_dhaka
        row.inside_enabled = payload.inside_enabled
        row.suburban_enabled = payload.suburban_enabled
        row.outside_enabled = payload.outside_enabled
    await db.commit()
    await db.refresh(row)
    return _read(row)
