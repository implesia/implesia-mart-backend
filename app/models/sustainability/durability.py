import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SustainabilityDurability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton durability block: cover photo and checked points."""

    __tablename__ = "sustainability_durabilities"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    image_src: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    image_alt: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<SustainabilityDurability {self.slug}>"


class SustainabilityDurabilityBullet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One checked line under the durability heading."""

    __tablename__ = "sustainability_durability_bullets"

    durability_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sustainability_durabilities.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<SustainabilityDurabilityBullet {self.sort_order}>"
