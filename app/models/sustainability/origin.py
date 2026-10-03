import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SustainabilityOrigin(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Singleton point-of-view block under the sustainability habits."""

    __tablename__ = "sustainability_origins"

    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    eyebrow: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    body: Mapped[str] = mapped_column(String(800), nullable=False, default="")
    quote: Mapped[str] = mapped_column(String(400), nullable=False, default="")

    def __repr__(self) -> str:
        return f"<SustainabilityOrigin {self.slug}>"


class SustainabilityOriginImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One photo beside the point of view. At most twelve."""

    __tablename__ = "sustainability_origin_images"

    origin_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sustainability_origins.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    src: Mapped[str] = mapped_column(String(255), nullable=False)
    alt: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<SustainabilityOriginImage {self.sort_order}>"
