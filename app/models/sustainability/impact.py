import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SustainabilityImpact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every stat does not recreate the defaults."""

    __tablename__ = "sustainability_impacts"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    kicker: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<SustainabilityImpact {self.slug}>"


class SustainabilityImpactItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One habit under the sustainability hero."""

    __tablename__ = "sustainability_impact_items"

    impact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sustainability_impacts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="verified")
    value: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<SustainabilityImpactItem {self.value}>"
