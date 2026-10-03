import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContactDetails(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton contact channels beside the message form."""

    __tablename__ = "contact_details"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    badge: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    facebook_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    facebook_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    facebook_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    linkedin_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    linkedin_href: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    linkedin_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<ContactDetails {self.slug}>"


class ContactDetailChannel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One way to reach the shop: call, chat, email, or a page."""

    __tablename__ = "contact_detail_channels"

    details_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contact_details.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="call")
    title: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    value: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    href: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ContactDetailChannel {self.sort_order}>"
