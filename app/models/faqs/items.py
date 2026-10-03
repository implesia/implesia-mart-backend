import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FaqQuestion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One question on the FAQ page."""

    __tablename__ = "faq_questions"

    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("faq_category_items.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    question: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    answer: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<FaqQuestion {self.sort_order}>"
