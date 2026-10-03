from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContactHero(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton banner at the top of the contact page."""

    __tablename__ = "contact_heroes"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    eyebrow: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    primary_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    primary_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    secondary_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    secondary_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ContactHero {self.slug}>"
