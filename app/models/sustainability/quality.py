import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SustainabilityQuality(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton quality block: cover photo, steps, and badges."""

    __tablename__ = "sustainability_qualities"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    image_src: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    image_alt: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<SustainabilityQuality {self.slug}>"


class SustainabilityQualityStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One numbered check beside the quality photo."""

    __tablename__ = "sustainability_quality_steps"

    quality_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sustainability_qualities.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<SustainabilityQualityStep {self.sort_order}>"


class SustainabilityQualityBadge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One short label under the quality steps."""

    __tablename__ = "sustainability_quality_badges"

    quality_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sustainability_qualities.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="check_circle")
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<SustainabilityQualityBadge {self.label}>"
