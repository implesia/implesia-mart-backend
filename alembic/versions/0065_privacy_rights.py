"""privacy rights

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "privacy_rights",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("nav_label", sa.String(length=80), nullable=False),
        sa.Column("heading", sa.String(length=200), nullable=False),
        sa.Column("intro", sa.String(length=800), nullable=False),
        sa.Column("retention_is_active", sa.Boolean(), nullable=False),
        sa.Column("retention_title", sa.String(length=200), nullable=False),
        sa.Column("retention_body", sa.String(length=800), nullable=False),
        sa.Column("updates_is_active", sa.Boolean(), nullable=False),
        sa.Column("updates_title", sa.String(length=200), nullable=False),
        sa.Column("updates_body", sa.String(length=800), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_rights")),
    )
    op.create_index(op.f("ix_privacy_rights_slug"), "privacy_rights", ["slug"], unique=True)
    op.create_table(
        "privacy_right_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rights_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=800), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["rights_id"],
            ["privacy_rights.id"],
            name="fk_privacy_right_items_rights_id_privacy_rights",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_right_items")),
    )
    op.create_index(
        op.f("ix_privacy_right_items_rights_id"),
        "privacy_right_items",
        ["rights_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_privacy_right_items_rights_id"), table_name="privacy_right_items")
    op.drop_table("privacy_right_items")
    op.drop_index(op.f("ix_privacy_rights_slug"), table_name="privacy_rights")
    op.drop_table("privacy_rights")
