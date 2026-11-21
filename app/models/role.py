from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """System and custom RBAC roles."""

    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint(
            "category IN ('staff', 'storefront')",
            name="ck_roles_category",
        ),
    )

    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="staff", nullable=False)
    admin_access: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<Role {self.slug} (admin_access={self.admin_access}, system={self.is_system})>"
