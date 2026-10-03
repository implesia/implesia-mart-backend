from pydantic import BaseModel, ConfigDict, Field


class DeliveryRatesRead(BaseModel):
    inside_dhaka: int
    dhaka_suburban: int
    outside_dhaka: int
    inside_enabled: bool
    suburban_enabled: bool
    outside_enabled: bool


class DeliveryRatesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inside_dhaka: int = Field(ge=0, le=1_000_000)
    dhaka_suburban: int = Field(ge=0, le=1_000_000)
    outside_dhaka: int = Field(ge=0, le=1_000_000)
    inside_enabled: bool
    suburban_enabled: bool
    outside_enabled: bool
