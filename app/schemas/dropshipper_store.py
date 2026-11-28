"""Pydantic schemas & strict XSS/hex validators for multi-tenant dropshipper storefronts."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.dropshipper_store import StoreTemplateId
from app.schemas.order import OrderTracking
from app.schemas.product import clean_line, clean_media_ref

RESERVED_STORE_SLUGS: frozenset[str] = frozenset(
    {
        "admin",
        "api",
        "dashboard",
        "dropshipper",
        "seller",
        "checkout",
        "products",
        "login",
        "register",
        "s",
        "store",
    }
)

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,78}[a-z0-9])?$")
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_META_PIXEL_RE = re.compile(r"^\d{10,20}$")
_GTM_RE = re.compile(r"^GTM-[A-Z0-9]{4,16}$")
_GA4_RE = re.compile(r"^G-[A-Z0-9]{6,16}$")
_TIKTOK_RE = re.compile(r"^[A-Z0-9]{8,32}$")
_SITE_VERIFICATION_RE = re.compile(r"^[A-Za-z0-9._-]{8,120}$")
_TEST_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")

StoreSectionType = Literal[
    "hero",
    "trust_badges",
    "featured_products",
    "categories",
    "all_products",
    "promo_banner",
    "reviews",
]


def _validate_hex(value: str) -> str:
    cleaned = value.strip()
    if not _HEX_RE.fullmatch(cleaned):
        raise ValueError("Color must be a valid 6-digit hex code like #4F46E5")
    return cleaned


def _validate_optional_pattern(
    value: str | None, pattern: re.Pattern[str], label: str
) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if "<" in cleaned or ">" in cleaned or not pattern.fullmatch(cleaned):
        raise ValueError(f"Invalid {label} format")
    return cleaned


class StoreThemeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_color: str = "#4F46E5"
    secondary_color: str = "#0F172A"
    accent_color: str = "#10B981"
    button_color: str = "#4F46E5"
    button_text_color: str = "#FFFFFF"
    header_bg: str = "#FFFFFF"
    background_color: str = "#F8FAFC"

    @field_validator(
        "primary_color",
        "secondary_color",
        "accent_color",
        "button_color",
        "button_text_color",
        "header_bg",
        "background_color",
    )
    @classmethod
    def _check_hex(cls, value: str) -> str:
        return _validate_hex(value)


class StoreBrandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_name: str = Field(default="", max_length=160)
    tagline: str = Field(default="", max_length=200)
    logo_url: str | None = Field(default=None, max_length=500)
    favicon_url: str | None = Field(default=None, max_length=500)
    phone: str = Field(default="", max_length=32)
    whatsapp: str = Field(default="", max_length=32)
    email: str = Field(default="", max_length=160)
    address: str = Field(default="", max_length=400)
    facebook_url: str = Field(default="", max_length=300)
    instagram_url: str = Field(default="", max_length=300)
    youtube_url: str = Field(default="", max_length=300)
    announcement_text: str = Field(default="", max_length=200)
    announcement_enabled: bool = False

    @field_validator(
        "shop_name",
        "tagline",
        "phone",
        "whatsapp",
        "email",
        "address",
        "announcement_text",
    )
    @classmethod
    def _clean_text(cls, value: str) -> str:
        return clean_line(value, 400)

    @field_validator("logo_url", "favicon_url")
    @classmethod
    def _clean_media(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return clean_media_ref(value)


class StoreHeroConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=160)
    subtitle: str = Field(default="", max_length=320)
    cta_text: str = Field(default="Shop Now", max_length=40)
    cta_href: str = Field(default="#products", max_length=200)
    banner_image_url: str | None = Field(default=None, max_length=500)
    mobile_banner_url: str | None = Field(default=None, max_length=500)

    @field_validator("title", "subtitle", "cta_text", "cta_href")
    @classmethod
    def _clean_hero(cls, value: str) -> str:
        return clean_line(value, 320)

    @field_validator("banner_image_url", "mobile_banner_url")
    @classmethod
    def _clean_hero_media(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return clean_media_ref(value)


class StoreSectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=48)
    type: StoreSectionType
    enabled: bool = True
    title: str = Field(default="", max_length=120)
    subtitle: str = Field(default="", max_length=240)
    order: int = Field(default=0, ge=0, le=100)


class DropshipperStoreRead(BaseModel):
    """Owner-facing store configuration. Masks meta_capi_token via has_meta_capi_token."""

    id: uuid.UUID
    dropshipper_id: uuid.UUID
    profile_id: uuid.UUID
    slug: str
    is_published: bool
    template_id: StoreTemplateId
    theme_config: StoreThemeConfig
    brand_config: StoreBrandConfig
    hero_config: StoreHeroConfig
    sections_config: list[StoreSectionConfig]
    seo_title: str
    seo_description: str
    seo_og_image_url: str | None
    google_site_verification: str | None
    bing_site_verification: str | None
    meta_pixel_id: str | None
    has_meta_capi_token: bool
    meta_test_event_code: str | None
    gtm_id: str | None
    ga4_measurement_id: str | None
    tiktok_pixel_id: str | None
    created_at: datetime
    updated_at: datetime


class DropshipperStoreUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(default=None, min_length=3, max_length=80)
    is_published: bool | None = None
    template_id: StoreTemplateId | None = None
    theme_config: StoreThemeConfig | None = None
    brand_config: StoreBrandConfig | None = None
    hero_config: StoreHeroConfig | None = None
    sections_config: list[StoreSectionConfig] | None = Field(default=None, max_length=20)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if cleaned in RESERVED_STORE_SLUGS:
            raise ValueError(f"Slug '{cleaned}' is reserved and cannot be used")
        if not _SLUG_RE.fullmatch(cleaned):
            raise ValueError(
                "Slug must be 3-80 lowercase letters, numbers, or hyphens "
                "(no leading/trailing hyphen)"
            )
        return cleaned


class DropshipperStoreSeoTrackingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seo_title: str | None = Field(default=None, max_length=120)
    seo_description: str | None = Field(default=None, max_length=320)
    seo_og_image_url: str | None = Field(default=None, max_length=500)
    google_site_verification: str | None = Field(default=None, max_length=120)
    bing_site_verification: str | None = Field(default=None, max_length=120)
    meta_pixel_id: str | None = Field(default=None, max_length=32)
    meta_capi_token: str | None = Field(default=None, max_length=512)
    meta_test_event_code: str | None = Field(default=None, max_length=64)
    gtm_id: str | None = Field(default=None, max_length=32)
    ga4_measurement_id: str | None = Field(default=None, max_length=32)
    tiktok_pixel_id: str | None = Field(default=None, max_length=40)

    @field_validator("seo_title", "seo_description")
    @classmethod
    def _clean_seo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_line(value, 320)

    @field_validator("seo_og_image_url")
    @classmethod
    def _clean_og(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return clean_media_ref(value)

    @field_validator("google_site_verification")
    @classmethod
    def _check_google(cls, value: str | None) -> str | None:
        return _validate_optional_pattern(value, _SITE_VERIFICATION_RE, "Google site verification")

    @field_validator("bing_site_verification")
    @classmethod
    def _check_bing(cls, value: str | None) -> str | None:
        return _validate_optional_pattern(value, _SITE_VERIFICATION_RE, "Bing site verification")

    @field_validator("meta_pixel_id")
    @classmethod
    def _check_meta_pixel(cls, value: str | None) -> str | None:
        return _validate_optional_pattern(value, _META_PIXEL_RE, "Meta Pixel ID")

    @field_validator("meta_test_event_code")
    @classmethod
    def _check_test_code(cls, value: str | None) -> str | None:
        return _validate_optional_pattern(value, _TEST_CODE_RE, "Meta Test Event Code")

    @field_validator("gtm_id")
    @classmethod
    def _check_gtm(cls, value: str | None) -> str | None:
        return _validate_optional_pattern(value, _GTM_RE, "Google Tag Manager ID")

    @field_validator("ga4_measurement_id")
    @classmethod
    def _check_ga4(cls, value: str | None) -> str | None:
        return _validate_optional_pattern(value, _GA4_RE, "GA4 Measurement ID")

    @field_validator("tiktok_pixel_id")
    @classmethod
    def _check_tiktok(cls, value: str | None) -> str | None:
        return _validate_optional_pattern(value, _TIKTOK_RE, "TikTok Pixel ID")

    @field_validator("meta_capi_token")
    @classmethod
    def _check_capi_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return ""
        if "<" in cleaned or ">" in cleaned or any(ch.isspace() for ch in cleaned):
            raise ValueError("Invalid Meta CAPI access token")
        return cleaned


class DropshipperStoreMediaUploadResponse(BaseModel):
    url: str
    field: Literal["hero_banner", "mobile_banner", "logo", "favicon", "og_image"]


class DropshipperStoreProductImportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    custom_title: str | None = Field(default=None, max_length=200)
    selling_price: int = Field(ge=1, le=10_000_000)
    compare_at_price: int | None = Field(default=None, ge=0, le=10_000_000)
    is_featured: bool = False
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=100_000)


class DropshipperStoreProductImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DropshipperStoreProductImportItem] = Field(min_length=1, max_length=50)


class DropshipperStoreProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    custom_title: str | None = Field(default=None, max_length=200)
    selling_price: int | None = Field(default=None, ge=1, le=10_000_000)
    compare_at_price: int | None = Field(default=None, ge=0, le=10_000_000)
    is_featured: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100_000)


class DropshipperStoreProductRead(BaseModel):
    """Owner-facing imported product row (dropship_price included; never cost_price)."""

    id: uuid.UUID
    store_id: uuid.UUID
    product_id: uuid.UUID
    product_slug: str
    title: str
    custom_title: str | None
    image_src: str
    dropship_price: int
    min_sell_price: int | None
    max_sell_price: int | None
    selling_price: int
    compare_at_price: int | None
    estimated_profit: int
    stock_quantity: int | None
    upstream_available: bool
    is_featured: bool
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class DropshipperStoreProductListResponse(BaseModel):
    items: list[DropshipperStoreProductRead]
    total: int


# ---------------------------------------------------------------------------
# Public Multi-Tenant Storefront Schemas (ZERO SECRET / WHOLESALE LEAKAGE)
# ---------------------------------------------------------------------------


class PublicStorefrontRead(BaseModel):
    """Public storefront payload. NEVER includes meta_capi_token or wholesale prices."""

    slug: str
    template_id: StoreTemplateId
    theme_config: StoreThemeConfig
    brand_config: StoreBrandConfig
    hero_config: StoreHeroConfig
    sections_config: list[StoreSectionConfig]
    seo_title: str
    seo_description: str
    seo_og_image_url: str | None
    google_site_verification: str | None
    bing_site_verification: str | None
    meta_pixel_id: str | None
    gtm_id: str | None
    ga4_measurement_id: str | None
    tiktok_pixel_id: str | None


class PublicStoreVariantRead(BaseModel):
    id: uuid.UUID
    options: dict[str, str]
    label: str
    sku: str
    selling_price: int
    stock_quantity: int | None
    weight_grams: int | None
    is_active: bool


class PublicStoreMediaItem(BaseModel):
    kind: Literal["image", "video", "youtube"]
    url: str
    youtube_id: str = ""
    thumbnail: str = ""
    alt: str = ""


class PublicStoreProductRead(BaseModel):
    """Public storefront product. NEVER exposes dropship_price, cost_price, or supplier_id."""

    id: uuid.UUID
    product_id: uuid.UUID
    slug: str
    title: str
    subtitle: str
    description: str
    category_slug: str
    category_name: str
    selling_price: int
    compare_at_price: int | None
    stock_quantity: int | None
    in_stock: bool
    weight_grams: int | None
    has_variants: bool
    is_featured: bool
    image_src: str
    media: list[PublicStoreMediaItem]
    variants: list[PublicStoreVariantRead]


class PublicStoreProductListResponse(BaseModel):
    items: list[PublicStoreProductRead]
    total: int
    page: int
    page_size: int
    pages: int


class PublicStoreOrderItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: int = Field(ge=1, le=100)


class PublicStoreOrderQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicStoreOrderItemInput] = Field(min_length=1, max_length=20)
    district: str = Field(default="Dhaka", min_length=2, max_length=80)
    area: str = Field(default="", max_length=120)
    delivery_zone: Literal["inside", "suburban", "outside"] | None = None


class PublicStoreOrderQuoteLine(BaseModel):
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    title: str
    slug: str
    image_src: str
    quantity: int
    unit_price: int
    line_total: int


class PublicStoreOrderQuoteResponse(BaseModel):
    lines: list[PublicStoreOrderQuoteLine]
    delivery_zone: str
    total_weight_grams: int
    subtotal: int
    shipping: int
    total: int


class PublicStoreOrderCreateRequest(PublicStoreOrderQuoteRequest):
    model_config = ConfigDict(extra="forbid")

    customer_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=32)
    address: str = Field(min_length=4, max_length=400)
    note: str = Field(default="", max_length=500)
    tracking: OrderTracking | None = None

    @field_validator("customer_name", "phone", "district", "area", "address", "note")
    @classmethod
    def _clean_public_order(cls, value: str) -> str:
        return clean_line(value, 500)


class PublicStoreOrderCreateResponse(BaseModel):
    order_number: str
    analytics_event_id: str
    status: str
    subtotal: int
    shipping: int
    total: int
    created_at: datetime
