import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RolePermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Database-backed module access override for a staff/partner role."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role", "module_key", name="uq_role_permissions_role_module"),
        CheckConstraint(
            "access_level IN ('none', 'read_only', 'read_write', 'full')",
            name="ck_role_permissions_access_level",
        ),
    )

    role: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("roles.slug", onupdate="CASCADE", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    module_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    access_level: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<RolePermission {self.role}:{self.module_key}={self.access_level}>"
