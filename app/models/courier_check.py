from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, UUIDPrimaryKeyMixin


class CourierCheckResult(UUIDPrimaryKeyMixin, Base):
    """One cached courier lookup for a normalized phone and one provider.

    The payload is the normalized result this API stores. It is not the raw
    courier body. Rows are replaced in place for the same phone and provider.
    """

    __tablename__ = "courier_check_results"
    __table_args__ = (
        UniqueConstraint(
            "phone",
            "provider",
            name="uq_courier_check_results_phone_provider",
        ),
    )

    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<CourierCheckResult {self.phone} {self.provider}>"
