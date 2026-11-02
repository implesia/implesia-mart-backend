from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

# A percentage with at most two decimals, 0 to 99.99. Sent to clients as a JSON number.
Percent = Annotated[
    Decimal,
    Field(ge=0, le=Decimal("99.99"), max_digits=4, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]
MAX_TIERS = 20


class QuantityTier(BaseModel):
    """Buy at least `min_quantity` and get `extra_percent` on top of the base discount."""

    model_config = ConfigDict(extra="forbid")

    min_quantity: int = Field(ge=2, le=1000)
    extra_percent: Percent


def _clean_tiers(tiers: list[QuantityTier]) -> list[QuantityTier]:
    quantities = [tier.min_quantity for tier in tiers]
    if len(set(quantities)) != len(quantities):
        raise ValueError("Each quantity tier needs a different quantity")
    return sorted(tiers, key=lambda tier: tier.min_quantity)


class PricingSettingsRead(BaseModel):
    tiers_enabled: bool
    max_discount_percent: Percent
    tiers: list[QuantityTier]


class PricingSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tiers_enabled: bool
    max_discount_percent: Percent
    tiers: list[QuantityTier] = Field(max_length=MAX_TIERS)

    @model_validator(mode="after")
    def _tiers(self) -> Self:
        self.tiers = _clean_tiers(self.tiers)
        return self


class ProductPricing(BaseModel):
    """What the product page needs to show the price for any quantity.

    The cart and checkout price lines on the server; this is for display only.
    """

    regular_price: int
    selling_price: int
    base_discount_percent: Percent
    max_discount_percent: Percent
    tiers: list[QuantityTier]


def clean_tiers(tiers: list[QuantityTier]) -> list[QuantityTier]:
    return _clean_tiers(tiers)
