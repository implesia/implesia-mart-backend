from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PrivacyHero(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton banner at the top of the privacy page."""

    __tablename__ = "privacy_heroes"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    eyebrow: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    updated_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    last_updated: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<PrivacyHero {self.slug}>"
