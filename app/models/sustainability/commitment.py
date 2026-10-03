import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SustainabilityCommitment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton row so deleting every card does not recreate the defaults."""

    __tablename__ = "sustainability_commitments"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    kicker: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    subtitle: Mapped[str] = mapped_column(String(400), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<SustainabilityCommitment {self.slug}>"


class SustainabilityCommitmentItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One responsibility card on the sustainability page."""

    __tablename__ = "sustainability_commitment_items"

    commitment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sustainability_commitments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="verified")
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<SustainabilityCommitmentItem {self.title}>"
