import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PrivacySharing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton sharing section on the privacy page."""

    __tablename__ = "privacy_sharings"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    nav_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    heading: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(800), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<PrivacySharing {self.slug}>"


class PrivacySharingChip(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One recipient chip in the privacy sharing section."""

    __tablename__ = "privacy_sharing_chips"

    sharing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("privacy_sharings.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<PrivacySharingChip {self.sort_order}>"
