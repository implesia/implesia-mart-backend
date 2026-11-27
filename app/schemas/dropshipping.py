"""Pydantic schemas for Dropshipping onboarding, catalog, and admin partner management."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.dropshipping import (
    DropshipperStatus,
    DropshipperTier,
    PayoutMethod,
    PayoutRequestStatus,
    RtoChargeMode,
    TopupRequestStatus,
    WalletBucket,
    WalletEntryType,
)
from app.schemas.product import clean_line, clean_media_ref


class DropshippingSettingsRead(BaseModel):
    enabled: bool
    registration_fee: int
    new_seller_max_active_orders: int
    trusted_delivery_threshold: int
    negative_wallet_limit: int
    payout_unlock_days: int
    require_cod_reconciled: bool
    min_withdrawal_amount: int
    rto_charge_mode: RtoChargeMode
    rto_fixed_fee: int
    platform_fee_percent: int
    packaging_fee_flat: int
    updated_at: datetime


class DropshippingSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    registration_fee: int | None = Field(default=None, ge=0, le=100_000)
    new_seller_max_active_orders: int | None = Field(default=None, ge=0, le=1_000)
    trusted_delivery_threshold: int | None = Field(default=None, ge=0, le=10_000)
    negative_wallet_limit: int | None = Field(default=None, le=0, ge=-1_000_000)
    payout_unlock_days: int | None = Field(default=None, ge=0, le=90)
    require_cod_reconciled: bool | None = None
    min_withdrawal_amount: int | None = Field(default=None, ge=0, le=1_000_000)
    rto_charge_mode: RtoChargeMode | None = None
    rto_fixed_fee: int | None = Field(default=None, ge=0, le=10_000)
    platform_fee_percent: int | None = Field(default=None, ge=0, le=100)
    packaging_fee_flat: int | None = Field(default=None, ge=0, le=10_000)


class DropshippingSettingsSummary(BaseModel):
    enabled: bool
    registration_fee: int
    new_seller_max_active_orders: int
    trusted_delivery_threshold: int
    payout_unlock_days: int
    min_withdrawal_amount: int
    rto_charge_mode: RtoChargeMode
    rto_fixed_fee: int
    platform_fee_percent: int
    packaging_fee_flat: int


class DropshipperApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_name: str = Field(min_length=2, max_length=160)
    shop_phone: str = Field(min_length=6, max_length=32)
    shop_slug: str | None = Field(default=None, max_length=80)
    shop_logo_url: str | None = Field(default=None, max_length=500)
    shop_address: str = Field(default="", max_length=400)
    business_url: str = Field(default="", max_length=300)
    nid_number: str = Field(default="", max_length=40)
    nid_front_url: str | None = Field(default=None, max_length=500)
    nid_back_url: str | None = Field(default=None, max_length=500)
    payout_method: PayoutMethod = PayoutMethod.BKASH
    payout_account_number: str = Field(min_length=4, max_length=64)
    payout_account_name: str = Field(default="", max_length=160)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_branch: str | None = Field(default=None, max_length=120)

    @field_validator("shop_name", "shop_phone", "shop_address", "nid_number", "payout_account_name")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        return clean_line(value, 400)

    @field_validator("shop_logo_url", "nid_front_url", "nid_back_url")
    @classmethod
    def _clean_media(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return clean_media_ref(value)


class DropshipperProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_name: str | None = Field(default=None, min_length=2, max_length=160)
    shop_phone: str | None = Field(default=None, min_length=6, max_length=32)
    shop_logo_url: str | None = Field(default=None, max_length=500)
    shop_address: str | None = Field(default=None, max_length=400)
    business_url: str | None = Field(default=None, max_length=300)
    payout_method: PayoutMethod | None = None
    payout_account_number: str | None = Field(default=None, min_length=4, max_length=64)
    payout_account_name: str | None = Field(default=None, max_length=160)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_branch: str | None = Field(default=None, max_length=120)

    @field_validator("shop_logo_url")
    @classmethod
    def _clean_logo(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return clean_media_ref(value)


class DropshipperProfileRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    status: DropshipperStatus
    tier: DropshipperTier
    shop_slug: str
    shop_name: str
    shop_phone: str
    shop_logo_url: str | None
    shop_address: str
    business_url: str
    nid_number: str
    nid_front_url: str | None
    nid_back_url: str | None
    payout_method: PayoutMethod
    payout_account_number: str
    payout_account_name: str
    bank_name: str | None
    bank_branch: str | None
    pending_balance: int
    available_balance: int
    locked_withdrawal_balance: int
    total_earned: int
    total_withdrawn: int
    delivered_count: int
    returned_count: int
    rto_rate: float
    rejection_reason: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DropshipperMeResponse(BaseModel):
    profile: DropshipperProfileRead | None
    settings: DropshippingSettingsSummary


class DropshipperUploadResponse(BaseModel):
    url: str
    field: Literal["shop_logo", "nid_front", "nid_back"]


class DropshipperCatalogVariant(BaseModel):
    id: uuid.UUID
    options: dict[str, str]
    label: str
    sku: str
    dropship_price: int
    suggested_retail_price: int
    stock_quantity: int | None
    weight_grams: int | None
    is_active: bool


class DropshipperCatalogMediaItem(BaseModel):
    kind: Literal["image", "video", "youtube"]
    url: str
    youtube_id: str = ""
    thumbnail: str = ""
    alt: str = ""


class DropshipperCatalogProduct(BaseModel):
    """Partner-facing wholesale catalog item. NEVER exposes cost_price or supplier_id."""

    id: uuid.UUID
    slug: str
    title: str
    subtitle: str
    category_id: uuid.UUID | None
    category_slug: str
    category_name: str
    dropship_price: int
    suggested_retail_price: int
    min_sell_price: int | None
    max_sell_price: int | None
    stock_quantity: int | None
    weight_grams: int | None
    status: str
    has_variants: bool
    image_src: str
    media: list[DropshipperCatalogMediaItem]
    variants: list[DropshipperCatalogVariant]


class DropshipperCatalogResponse(BaseModel):
    items: list[DropshipperCatalogProduct]
    total: int
    page: int
    page_size: int
    pages: int


class AdminDropshipperPartnerRead(DropshipperProfileRead):
    user_full_name: str
    user_email: str | None
    user_phone: str | None
    user_role: str


class AdminDropshipperListResponse(BaseModel):
    items: list[AdminDropshipperPartnerRead]
    total: int
    page: int
    page_size: int
    pages: int


class AdminDropshippingOverview(BaseModel):
    enabled: bool
    total_partners: int
    pending_count: int
    approved_count: int
    rejected_count: int
    suspended_count: int
    catalog_products_count: int
    total_pending_balance: int
    total_available_balance: int
    total_locked_balance: int


class AdminRejectPartnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class AdminSuspendPartnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# Phase 32: Dropshipper Order Engine, Wallet Ledger, Payouts & Top-Ups
# ---------------------------------------------------------------------------


class DropshipOrderItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: int = Field(ge=1, le=500)
    selling_price: int = Field(ge=1, le=10_000_000)


class DropshipOrderQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DropshipOrderItemInput] = Field(min_length=1, max_length=50)
    district: str = Field(default="Dhaka", min_length=2, max_length=80)
    area: str = Field(default="", max_length=120)
    delivery_zone: Literal[
        "inside", "suburban", "outside", "dhaka_inside", "dhaka_suburb", "outside_dhaka"
    ] | None = None

    @field_validator("delivery_zone")
    @classmethod
    def _normalize_zone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        mapping = {
            "dhaka_inside": "inside",
            "dhaka_suburb": "suburban",
            "outside_dhaka": "outside",
        }
        return mapping.get(value, value)


class DropshipOrderQuoteLine(BaseModel):
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    title: str
    slug: str
    image_src: str
    sku: str
    quantity: int
    wholesale_price: int
    selling_price: int
    wholesale_total: int
    selling_total: int
    weight_grams: int


class DropshipOrderQuoteResponse(BaseModel):
    lines: list[DropshipOrderQuoteLine]
    delivery_zone: str
    total_weight_grams: int
    shipping: int
    weight_surcharge: int
    wholesale_total: int
    platform_fee: int
    customer_subtotal: int
    customer_total: int
    profit_amount: int
    can_place_order: bool = True
    blocked_reason: str | None = None


class DropshipOrderCreateRequest(DropshipOrderQuoteRequest):
    model_config = ConfigDict(extra="forbid")

    customer_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=32)
    address: str = Field(min_length=4, max_length=400)
    note: str = Field(default="", max_length=500)

    @field_validator("customer_name", "phone", "district", "area", "address", "note")
    @classmethod
    def _clean_order_text(cls, value: str) -> str:
        return clean_line(value, 500)


class DropshipOrderItemRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    variant_id: uuid.UUID | None
    title: str
    slug: str
    image_src: str
    sku: str
    quantity: int
    unit_price: int
    line_total: int


class DropshipOrderSummary(BaseModel):
    id: uuid.UUID
    number: str
    status: str
    customer_name: str
    phone: str
    district: str
    area: str
    customer_subtotal: int
    shipping: int
    customer_total: int
    wholesale_total: int
    platform_fee: int
    profit_amount: int
    courier_name: str | None
    tracking_number: str | None
    items_count: int
    first_item_title: str | None
    first_item_image: str | None
    created_at: datetime
    delivered_at: datetime | None
    returned_at: datetime | None


class DropshipOrderDetail(DropshipOrderSummary):
    address: str
    note: str
    delivery_zone: str
    white_label_shop_name: str | None
    white_label_shop_phone: str | None
    white_label_logo_url: str | None
    items: list[DropshipOrderItemRead]


class DropshipOrderListResponse(BaseModel):
    items: list[DropshipOrderSummary]
    total: int
    page: int
    page_size: int
    pages: int


class DropshipOrderTrackingEvent(BaseModel):
    status: str
    message: str = ""
    timestamp: str | None = None
    source: str = "courier"


class DropshipOrderTrackingResponse(BaseModel):
    order_number: str
    order_status: str
    courier_name: str | None
    tracking_number: str | None
    consignment_id: str | None
    delivery_status: str | None
    return_status: str | None
    is_final: bool = False
    is_return_received: bool = False
    last_synced_at: datetime | None = None
    events: list[DropshipOrderTrackingEvent]


class DropshipperWalletSummary(BaseModel):
    pending_balance: int
    available_balance: int
    locked_withdrawal_balance: int
    total_earned: int
    total_withdrawn: int
    delivered_count: int
    returned_count: int
    rto_rate: float
    tier: DropshipperTier
    status: DropshipperStatus
    active_orders_count: int
    new_seller_max_active_orders: int
    trusted_delivery_threshold: int
    negative_wallet_limit: int
    min_withdrawal_amount: int
    payout_unlock_days: int
    is_blocked_negative_wallet: bool
    unlocked_just_now: int = 0


class DropshipperWalletTransactionRead(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID | None
    payout_id: uuid.UUID | None
    topup_id: uuid.UUID | None
    entry_type: WalletEntryType
    amount: int
    balance_bucket: WalletBucket
    unlock_at: datetime | None
    unlocked_at: datetime | None
    note: str
    created_at: datetime


class DropshipperWalletTransactionListResponse(BaseModel):
    items: list[DropshipperWalletTransactionRead]
    total: int
    page: int
    page_size: int
    pages: int


class DropshipperPayoutCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(ge=1, le=10_000_000)
    payout_method: PayoutMethod | None = None
    payout_account_number: str | None = Field(default=None, min_length=4, max_length=64)
    payout_account_name: str | None = Field(default=None, max_length=160)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_branch: str | None = Field(default=None, max_length=120)


class DropshipperPayoutRead(BaseModel):
    id: uuid.UUID
    dropshipper_id: uuid.UUID
    amount: int
    status: PayoutRequestStatus
    payout_method: PayoutMethod
    payout_account_number: str
    payout_account_name: str
    bank_name: str | None
    bank_branch: str | None
    transaction_id: str | None
    admin_note: str
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminDropshipperPayoutRead(DropshipperPayoutRead):
    shop_name: str
    shop_phone: str
    user_full_name: str


class DropshipperPayoutListResponse(BaseModel):
    items: list[DropshipperPayoutRead]
    total: int
    page: int
    page_size: int
    pages: int


class AdminDropshipperPayoutListResponse(BaseModel):
    items: list[AdminDropshipperPayoutRead]
    total: int
    page: int
    page_size: int
    pages: int


class AdminPayoutMarkPaidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=2, max_length=120)
    admin_note: str = Field(default="", max_length=500)


class AdminPayoutRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class DropshipperTopupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(ge=1, le=10_000_000)
    payment_method: str = Field(min_length=2, max_length=32)
    sender_number: str = Field(min_length=6, max_length=32)
    transaction_id: str = Field(min_length=2, max_length=120)

    @field_validator("payment_method", "sender_number", "transaction_id")
    @classmethod
    def _clean_topup(cls, value: str) -> str:
        return clean_line(value, 120)


class DropshipperTopupRead(BaseModel):
    id: uuid.UUID
    dropshipper_id: uuid.UUID
    amount: int
    payment_method: str
    sender_number: str
    transaction_id: str
    status: TopupRequestStatus
    admin_note: str
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminDropshipperTopupRead(DropshipperTopupRead):
    shop_name: str
    shop_phone: str
    user_full_name: str


class DropshipperTopupListResponse(BaseModel):
    items: list[DropshipperTopupRead]
    total: int
    page: int
    page_size: int
    pages: int


class AdminDropshipperTopupListResponse(BaseModel):
    items: list[AdminDropshipperTopupRead]
    total: int
    page: int
    page_size: int
    pages: int


class AdminTopupApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_note: str = Field(default="", max_length=500)


class AdminTopupRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class AdminWalletAdjustRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: int = Field(ge=-10_000_000, le=10_000_000)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("amount")
    @classmethod
    def _non_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("Adjustment amount cannot be zero")
        return value
