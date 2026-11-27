from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(StrEnum):
    SUPERADMIN = "superadmin"
    EDITOR = "editor"
    VIEWER = "viewer"
    CUSTOMER = "customer"
    DROPSHIPPER = "dropshipper"


# Staff roles allowed to sign into /admin. Future non-staff roles (e.g. dropshipper)
# stay outside this set so core admin guards never need to change.
STAFF_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.VIEWER, UserRole.EDITOR, UserRole.SUPERADMIN}
)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index(
            "ix_users_phone",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
    )

    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    district: Mapped[str | None] = mapped_column(String(80), nullable=True)
    area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("roles.slug", onupdate="CASCADE", ondelete="RESTRICT"),
        index=True,
        default=UserRole.VIEWER.value,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        ident = self.phone or self.email or str(self.id)
        return f"<User {ident} ({self.role})>"
