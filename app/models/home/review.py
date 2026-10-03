import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class HomeReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every review does not recreate the defaults."""

    __tablename__ = "home_reviews"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    kicker: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<HomeReview {self.slug}>"


class HomeReviewItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One customer screenshot in the home review row."""

    __tablename__ = "home_review_items"

    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("home_reviews.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    product: Mapped[str] = mapped_column(String(120), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    image_src: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    image_alt: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<HomeReviewItem {self.product}>"
