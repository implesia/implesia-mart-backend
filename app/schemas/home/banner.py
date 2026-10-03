import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.home.banner import BannerAccent


def _href(value: str) -> str:
    if not (value.startswith("/") or value.startswith("http://") or value.startswith("https://")):
        raise ValueError("href must start with / or http")
    return value


class BannerCta(BaseModel):
    label: str
    href: str


class BannerSlidePublic(BaseModel):
    id: uuid.UUID
    slug: str
    eyebrow: str
    title: str
    description: str
    price: int
    compare_at_price: int | None
    price_prefix: str | None
    price_label: str
    compare_at_label: str | None
    discount_label: str | None
    primary_cta: BannerCta
    secondary_cta: BannerCta
    image_src: str
    image_alt: str
    image_priority: bool
    accent: BannerAccent


class HomeBannerPublic(BaseModel):
    brand_name: str
    aria_label: str
    trust_line: str
    previous_label: str
    next_label: str
    slide_label: str
    autoplay_delay_ms: int
    transition_speed_ms: int
    pause_on_hover: bool
    loop: bool
    keyboard_enabled: bool
    disable_on_interaction: bool
    cross_fade: bool
    effect: str = "fade"
    slides: list[BannerSlidePublic]


class HomeBannerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    brand_name: str
    aria_label: str
    trust_line: str
    previous_label: str
    next_label: str
    slide_label: str
    autoplay_delay_ms: int
    transition_speed_ms: int
    pause_on_hover: bool
    loop: bool
    keyboard_enabled: bool
    disable_on_interaction: bool
    cross_fade: bool
    effect: str = "fade"
    updated_at: datetime


class HomeBannerUpdate(BaseModel):
    brand_name: str | None = Field(None, min_length=1, max_length=80)
    aria_label: str | None = Field(None, min_length=1, max_length=120)
    trust_line: str | None = Field(None, min_length=1, max_length=200)
    previous_label: str | None = Field(None, min_length=1, max_length=80)
    next_label: str | None = Field(None, min_length=1, max_length=80)
    slide_label: str | None = Field(None, min_length=1, max_length=40)
    autoplay_delay_ms: int | None = Field(None, ge=1000, le=60000)
    transition_speed_ms: int | None = Field(None, ge=100, le=5000)
    pause_on_hover: bool | None = None
    loop: bool | None = None
    keyboard_enabled: bool | None = None
    disable_on_interaction: bool | None = None
    cross_fade: bool | None = None


class BannerSlideAdmin(BannerSlidePublic):
    sort_order: int
    is_published: bool
    internal_notes: str | None
    created_at: datetime
    updated_at: datetime


class BannerSlideWrite(BaseModel):
    slug: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    eyebrow: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    price: int = Field(ge=0)
    compare_at_price: int | None = Field(None, ge=0)
    price_prefix: str | None = Field(None, max_length=40)
    primary_cta_label: str = Field(min_length=1, max_length=80)
    primary_cta_href: str = Field(min_length=1, max_length=255)
    secondary_cta_label: str = Field(min_length=1, max_length=80)
    secondary_cta_href: str = Field(min_length=1, max_length=255)
    image_src: str = Field(min_length=1, max_length=255)
    image_alt: str = Field(min_length=1, max_length=200)
    accent: BannerAccent = BannerAccent.GOLD
    sort_order: int = Field(0, ge=0, le=1000)
    is_published: bool = True
    internal_notes: str | None = Field(None, max_length=4000)

    @field_validator("primary_cta_href", "secondary_cta_href")
    @classmethod
    def _check_href(cls, value: str) -> str:
        return _href(value)

    @field_validator("price_prefix")
    @classmethod
    def _blank_prefix(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class BannerSlideUpdate(BaseModel):
    slug: str | None = Field(
        None, min_length=1, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    eyebrow: str | None = Field(None, min_length=1, max_length=120)
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, min_length=1, max_length=2000)
    price: int | None = Field(None, ge=0)
    compare_at_price: int | None = Field(None, ge=0)
    price_prefix: str | None = Field(None, max_length=40)
    primary_cta_label: str | None = Field(None, min_length=1, max_length=80)
    primary_cta_href: str | None = Field(None, min_length=1, max_length=255)
    secondary_cta_label: str | None = Field(None, min_length=1, max_length=80)
    secondary_cta_href: str | None = Field(None, min_length=1, max_length=255)
    image_src: str | None = Field(None, min_length=1, max_length=255)
    image_alt: str | None = Field(None, min_length=1, max_length=200)
    accent: BannerAccent | None = None
    sort_order: int | None = Field(None, ge=0, le=1000)
    is_published: bool | None = None
    internal_notes: str | None = Field(None, max_length=4000)

    @field_validator("primary_cta_href", "secondary_cta_href")
    @classmethod
    def _check_href(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _href(value)

    @field_validator("price_prefix")
    @classmethod
    def _blank_prefix(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
