import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.order import Order
from app.models.product import Product
from app.models.user import User


class ProductReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_product_reviews_rating_range"),
        Index(
            "ix_product_reviews_product_id_is_published_created_at",
            "product_id",
            "is_published",
            "created_at",
        ),
        Index("ix_product_reviews_user_product", "user_id", "product_id"),
        Index("ix_product_reviews_order_id", "order_id"),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
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
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    headline: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    comment: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    is_verified_purchase: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id], lazy="selectin")
    product: Mapped[Product | None] = relationship(
        "Product", foreign_keys=[product_id], lazy="noload"
    )
    order: Mapped[Order | None] = relationship("Order", foreign_keys=[order_id], lazy="noload")

    def __repr__(self) -> str:
        return f"<ProductReview {self.id} (product={self.product_id}, rating={self.rating})>"
