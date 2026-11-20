"""customer role and profile fields on user

Revision ID: 0102
Revises: 0101
Create Date: 2026-11-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0102"
down_revision: str | None = "0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add 'customer' value to user_role enum
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'customer'")

    # Add profile columns to users table
    op.add_column("users", sa.Column("phone", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("district", sa.String(length=80), nullable=True))
    op.add_column("users", sa.Column("area", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("address", sa.String(length=500), nullable=True))

    # Allow email to be nullable for phone-only customer accounts
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=True)

    # Partial unique index on phone: unique where phone is not null
    op.create_index(
        "ix_users_phone",
        "users",
        ["phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_phone", table_name="users")
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=False)
    op.drop_column("users", "address")
    op.drop_column("users", "area")
    op.drop_column("users", "district")
    op.drop_column("users", "phone")
