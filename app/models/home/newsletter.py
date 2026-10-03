import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HomeNewsletter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every perk does not recreate the defaults."""

    __tablename__ = "home_newsletters"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    eyebrow: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    placeholder: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    cta: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    success: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<HomeNewsletter {self.slug}>"


class HomeNewsletterPerk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One short line under the home subscribe form."""

    __tablename__ = "home_newsletter_perks"

    newsletter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("home_newsletters.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<HomeNewsletterPerk {self.label}>"
