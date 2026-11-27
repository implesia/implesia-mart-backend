from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_SUBURBAN_PLACES: tuple[str, ...] = (
    "Savar",
    "Ashulia",
    "Gazipur",
    "Keraniganj",
    "Narayanganj",
)


class DeliveryRatesRead(BaseModel):
    inside_dhaka: int
    dhaka_suburban: int
    outside_dhaka: int
    inside_enabled: bool
    suburban_enabled: bool
    outside_enabled: bool
    weight_pricing_enabled: bool = True
    base_weight_grams: int = 1000
    extra_weight_step_grams: int = 1000
    extra_fee_inside: int = 20
    extra_fee_suburban: int = 20
    extra_fee_outside: int = 20
    packaging_weight_grams: int = 0
    default_product_weight_grams: int = 500
    suburban_places: list[str] = Field(default_factory=lambda: list(DEFAULT_SUBURBAN_PLACES))


class DeliveryRatesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inside_dhaka: int = Field(ge=0, le=1_000_000)
    dhaka_suburban: int = Field(ge=0, le=1_000_000)
    outside_dhaka: int = Field(ge=0, le=1_000_000)
    inside_enabled: bool
    suburban_enabled: bool
    outside_enabled: bool
    weight_pricing_enabled: bool | None = None
    base_weight_grams: int | None = Field(default=None, ge=1, le=1_000_000)
    extra_weight_step_grams: int | None = Field(default=None, ge=1, le=1_000_000)
    extra_fee_inside: int | None = Field(default=None, ge=0, le=1_000_000)
    extra_fee_suburban: int | None = Field(default=None, ge=0, le=1_000_000)
    extra_fee_outside: int | None = Field(default=None, ge=0, le=1_000_000)
    packaging_weight_grams: int | None = Field(default=None, ge=0, le=100_000)
    default_product_weight_grams: int | None = Field(default=None, ge=0, le=1_000_000)
    suburban_places: list[str] | None = Field(default=None, max_length=100)

    @field_validator("suburban_places")
    @classmethod
    def _clean_suburban_places(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            name = " ".join(raw.split()).strip()
            if not name:
                continue
            if len(name) > 80:
                raise ValueError("Each suburban place name must be at most 80 characters")
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(name)
        return cleaned
