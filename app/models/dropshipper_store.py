"""Multi-tenant dropshipper storefront configuration and imported product catalog."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.dropshipping import DropshipperProfile
from app.models.product import Product


class StoreTemplateId(StrEnum):
    MODERN_TECH = "modern_tech"
    MINIMAL_BOUTIQUE = "minimal_boutique"
    FLASH_DEAL = "flash_deal"


def _json_col() -> Any:
    return JSON().with_variant(JSONB(), "postgresql")


class DropshipperStore(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Partner-branded multi-tenant storefront (3 templates, dynamic SEO & tracking)."""

    __tablename__ = "dropshipper_stores"
    __table_args__ = (
        UniqueConstraint("dropshipper_id", name="uq_dropshipper_stores_dropshipper_id"),
        UniqueConstraint("profile_id", name="uq_dropshipper_stores_profile_id"),
        UniqueConstraint("slug", name="uq_dropshipper_stores_slug"),
        CheckConstraint(
            "template_id IN ('modern_tech', 'minimal_boutique', 'flash_deal')",
            name="template_id_known",
        ),
        Index("ix_dropshipper_stores_slug", "slug", unique=True),
        Index("ix_dropshipper_stores_is_published", "is_published"),
    )

    dropshipper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dropshipper_profiles.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    template_id: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=StoreTemplateId.MODERN_TECH.value,
        server_default=StoreTemplateId.MODERN_TECH.value,
    )

    theme_config: Mapped[dict[str, Any]] = mapped_column(_json_col(), nullable=False, default=dict)
    brand_config: Mapped[dict[str, Any]] = mapped_column(_json_col(), nullable=False, default=dict)
    hero_config: Mapped[dict[str, Any]] = mapped_column(_json_col(), nullable=False, default=dict)
    sections_config: Mapped[list[dict[str, Any]]] = mapped_column(
        _json_col(), nullable=False, default=list
    )

    seo_title: Mapped[str] = mapped_column(
        String(120), nullable=False, default="", server_default=""
    )
    seo_description: Mapped[str] = mapped_column(
        String(320), nullable=False, default="", server_default=""
    )
    seo_og_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    google_site_verification: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bing_site_verification: Mapped[str | None] = mapped_column(String(120), nullable=True)
    meta_pixel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    meta_capi_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta_test_event_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gtm_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ga4_measurement_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tiktok_pixel_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    profile: Mapped[DropshipperProfile] = relationship(foreign_keys=[profile_id])


class DropshipperStoreProduct(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Product imported from Implesia Mart wholesale catalog into a dropshipper storefront."""

    __tablename__ = "dropshipper_store_products"
    __table_args__ = (
        UniqueConstraint(
            "store_id",
            "product_id",
            name="uq_dropshipper_store_products_store_product",
        ),
        CheckConstraint("selling_price >= 0", name="selling_price_non_negative"),
        CheckConstraint(
            "compare_at_price IS NULL OR compare_at_price >= 0",
            name="compare_at_non_negative",
        ),
        Index("ix_dropshipper_store_products_store_id", "store_id"),
        Index("ix_dropshipper_store_products_product_id", "product_id"),
    )

    store_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dropshipper_stores.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    custom_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    selling_price: Mapped[int] = mapped_column(Integer, nullable=False)
    compare_at_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_featured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    store: Mapped[DropshipperStore] = relationship(foreign_keys=[store_id])
    product: Mapped[Product] = relationship(foreign_keys=[product_id])
