from sqlalchemy import CheckConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DeliverySettings(TimestampMixin, Base):
    """City, Dhaka-suburban, and outside-Dhaka cash-on-delivery rates. One row, id 1."""

    __tablename__ = "delivery_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(
            "inside_dhaka >= 0 AND dhaka_suburban >= 0 AND outside_dhaka >= 0",
            name="fees_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inside_dhaka: Mapped[int] = mapped_column(Integer, nullable=False)
    dhaka_suburban: Mapped[int] = mapped_column(Integer, nullable=False)
    outside_dhaka: Mapped[int] = mapped_column(Integer, nullable=False)
