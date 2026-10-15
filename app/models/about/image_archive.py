import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AboutImageArchive(Base):
    """Photos removed when About sections went to a single image (migration 0071).

    Read-only history: nothing in the app writes here. ``alembic downgrade 0070`` moves
    these rows back into their source tables.
    """

    __tablename__ = "about_image_archive"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source_table: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    src: Mapped[str] = mapped_column(String(255), nullable=False)
    alt: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
