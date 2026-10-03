import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContactSupport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton support hours and quick links on the contact page."""

    __tablename__ = "contact_supports"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<ContactSupport {self.slug}>"


class ContactSupportHour(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row of support hours."""

    __tablename__ = "contact_support_hours"

    support_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact_supports.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    value: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ContactSupportHour {self.sort_order}>"


class ContactSupportLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One shortcut beside the support hours."""

    __tablename__ = "contact_support_links"

    support_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact_supports.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="help")
    label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    href: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ContactSupportLink {self.sort_order}>"
