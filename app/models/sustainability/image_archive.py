import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SustainabilityImageArchive(Base):
    """Photos removed when sustainability sections went to one optional image (0072).

    Read-only history: nothing in the app writes here. ``alembic downgrade 0071`` moves
    these rows back into their source tables.
    """

    __tablename__ = "sustainability_image_archive"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source_table: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    src: Mapped[str] = mapped_column(String(255), nullable=False)
    alt: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
