import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.order import Order
from app.models.user import User


class CustomerNotification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customer_notifications"
    __table_args__ = (
        Index("ix_customer_notifications_user_id_created_at", "user_id", "created_at"),
        Index("ix_customer_notifications_user_id_is_read", "user_id", "is_read"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[str] = mapped_column(String(32), default="order_status", nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="bn", nullable=False)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="selectin")
    order: Mapped[Order | None] = relationship("Order", foreign_keys=[order_id], lazy="selectin")

    def __repr__(self) -> str:
        return f"<CustomerNotification {self.id} (user={self.user_id}, read={self.is_read})>"
