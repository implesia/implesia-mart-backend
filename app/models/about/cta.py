from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AboutCta(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton closing block on the about page."""

    __tablename__ = "about_cta"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    primary_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    primary_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    secondary_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    secondary_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<AboutCta {self.slug}>"
