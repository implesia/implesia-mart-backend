"""privacy sharing

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "privacy_sharings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("nav_label", sa.String(length=80), nullable=False),
        sa.Column("heading", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=800), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_sharings")),
    )
    op.create_index(op.f("ix_privacy_sharings_slug"), "privacy_sharings", ["slug"], unique=True)
    op.create_table(
        "privacy_sharing_chips",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sharing_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["sharing_id"],
            ["privacy_sharings.id"],
            name="fk_privacy_sharing_chips_sharing_id_privacy_sharings",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_sharing_chips")),
    )
    op.create_index(
        op.f("ix_privacy_sharing_chips_sharing_id"),
        "privacy_sharing_chips",
        ["sharing_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_privacy_sharing_chips_sharing_id"), table_name="privacy_sharing_chips"
    )
    op.drop_table("privacy_sharing_chips")
    op.drop_index(op.f("ix_privacy_sharings_slug"), table_name="privacy_sharings")
    op.drop_table("privacy_sharings")
