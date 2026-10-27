import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class InquiryType(StrEnum):
    NEWSLETTER = "newsletter"
    CONTACT = "contact"
    PRODUCT_INQUIRY = "product_inquiry"
    ORDER_HELP = "order_help"
    OTHER = "other"


class InquiryStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class Inquiry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A message or sign-up left by a visitor. Every visitor field is optional.

    Text is stored exactly as plain text (never HTML) and escaped when rendered.
    No IP address is stored; rate limiting uses a salted hash in Redis only.
    """

    __tablename__ = "inquiries"
    __table_args__ = (
        Index("ix_inquiries_status_created", "status", "created_at"),
        Index("ix_inquiries_type_created", "type", "created_at"),
        CheckConstraint(
            "type IN ('newsletter','contact','product_inquiry','order_help','other')", name="type"
        ),
        CheckConstraint("status IN ('new','in_progress','resolved')", name="status"),
    )

    public_id: Mapped[uuid.UUID] = mapped_column(unique=True, nullable=False, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=InquiryStatus.NEW.value)
    name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="", index=True)
    phone: Mapped[str] = mapped_column(String(15), nullable=False, default="", index=True)
    subject: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Safe, whitelisted context only: page path, product id/slug, topic.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    admin_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    handled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)

    def __repr__(self) -> str:
        return f"<Inquiry {self.type} {self.status}>"
