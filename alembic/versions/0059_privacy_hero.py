"""privacy hero

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "privacy_heroes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("eyebrow", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column("updated_label", sa.String(length=80), nullable=False),
        sa.Column("last_updated", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_heroes")),
    )
    op.create_index(op.f("ix_privacy_heroes_slug"), "privacy_heroes", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_privacy_heroes_slug"), table_name="privacy_heroes")
    op.drop_table("privacy_heroes")
