import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, UUIDPrimaryKeyMixin


class AuditAction(StrEnum):
    PRODUCT_PRICE_UPDATED = "PRODUCT_PRICE_UPDATED"
    PRODUCT_STOCK_UPDATED = "PRODUCT_STOCK_UPDATED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    ROLE_CHANGED = "ROLE_CHANGED"
    USER_DISABLED = "USER_DISABLED"


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """One admin change. Rows are inserted with the change and never updated.

    The column is ``metadata``. The attribute is ``event_metadata`` because
    ``metadata`` is already used by the SQLAlchemy base.
    """

    __tablename__ = "audit_events"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )

    def __repr__(self) -> str:
        return f"<AuditEvent {self.action} {self.target_type}:{self.target_id}>"
