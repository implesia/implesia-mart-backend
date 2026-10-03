import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FaqHero(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton banner and search at the top of the FAQ page."""

    __tablename__ = "faq_heroes"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    eyebrow: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    placeholder: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    search_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    clear_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    trending_label: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<FaqHero {self.slug}>"


class FaqHeroSearch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One quick-search chip on the FAQ hero."""

    __tablename__ = "faq_hero_searches"

    hero_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("faq_heroes.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<FaqHeroSearch {self.sort_order}>"
