import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AboutStats(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every stat does not recreate the defaults."""

    __tablename__ = "about_stats"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)

    def __repr__(self) -> str:
        return f"<AboutStats {self.slug}>"


class AboutStatItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One number on the about-page stats bar."""

    __tablename__ = "about_stat_items"

    stats_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("about_stats.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AboutStatItem {self.value}>"
