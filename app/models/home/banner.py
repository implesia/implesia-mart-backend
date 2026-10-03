import uuid
from enum import StrEnum

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BannerAccent(StrEnum):
    GOLD = "gold"
    TEAL = "teal"
    ROSE = "rose"
    INK = "ink"


class HomeBanner(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Chrome for the home hero: brand line, trust copy, and carousel timing."""

    __tablename__ = "home_banners"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    brand_name: Mapped[str] = mapped_column(String(80), nullable=False)
    aria_label: Mapped[str] = mapped_column(String(120), nullable=False)
    trust_line: Mapped[str] = mapped_column(String(200), nullable=False)
    previous_label: Mapped[str] = mapped_column(String(80), nullable=False)
    next_label: Mapped[str] = mapped_column(String(80), nullable=False)
    slide_label: Mapped[str] = mapped_column(String(40), nullable=False)
    autoplay_delay_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    transition_speed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    pause_on_hover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    loop: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    keyboard_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    disable_on_interaction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cross_fade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<HomeBanner {self.slug}>"


class HomeBannerSlide(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One slide in the home hero carousel."""

    __tablename__ = "home_banner_slides"

    banner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("home_banners.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True, nullable=False)
    eyebrow: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    compare_at_price: Mapped[int | None] = mapped_column(Integer)
    price_prefix: Mapped[str | None] = mapped_column(String(40))
    price_text: Mapped[str | None] = mapped_column(String(80))
    primary_cta_label: Mapped[str] = mapped_column(String(80), nullable=False)
    primary_cta_href: Mapped[str] = mapped_column(String(255), nullable=False)
    secondary_cta_label: Mapped[str] = mapped_column(String(80), nullable=False)
    secondary_cta_href: Mapped[str] = mapped_column(String(255), nullable=False)
    image_src: Mapped[str] = mapped_column(String(255), nullable=False)
    image_alt: Mapped[str] = mapped_column(String(200), nullable=False)
    accent: Mapped[BannerAccent] = mapped_column(
        Enum(BannerAccent, name="banner_accent", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    internal_notes: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<HomeBannerSlide {self.slug}>"
