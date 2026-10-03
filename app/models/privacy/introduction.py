import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PrivacyIntroduction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton opening section on the privacy page."""

    __tablename__ = "privacy_intros"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    nav_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    heading: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<PrivacyIntroduction {self.slug}>"


class PrivacyIntroductionParagraph(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One paragraph in the privacy introduction."""

    __tablename__ = "privacy_intro_paragraphs"

    intro_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("privacy_intros.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<PrivacyIntroductionParagraph {self.sort_order}>"
