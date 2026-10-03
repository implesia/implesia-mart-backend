"""privacy usage

Revision ID: 0063
Revises: 0062
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "privacy_usages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("nav_label", sa.String(length=80), nullable=False),
        sa.Column("heading", sa.String(length=200), nullable=False),
        sa.Column("intro", sa.String(length=800), nullable=False),
        sa.Column("protection_is_active", sa.Boolean(), nullable=False),
        sa.Column("protection_icon", sa.String(length=40), nullable=False),
        sa.Column("protection_title", sa.String(length=200), nullable=False),
        sa.Column("protection_body", sa.String(length=800), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_usages")),
    )
    op.create_index(op.f("ix_privacy_usages_slug"), "privacy_usages", ["slug"], unique=True)
    op.create_table(
        "privacy_usage_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("usage_id", sa.Uuid(), nullable=False),
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
            ["usage_id"],
            ["privacy_usages.id"],
            name="fk_privacy_usage_items_usage_id_privacy_usages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_usage_items")),
    )
    op.create_index(
        op.f("ix_privacy_usage_items_usage_id"),
        "privacy_usage_items",
        ["usage_id"],
        unique=False,
    )
    op.create_table(
        "privacy_usage_badges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("usage_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
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
            ["usage_id"],
            ["privacy_usages.id"],
            name="fk_privacy_usage_badges_usage_id_privacy_usages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_usage_badges")),
    )
    op.create_index(
        op.f("ix_privacy_usage_badges_usage_id"),
        "privacy_usage_badges",
        ["usage_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_privacy_usage_badges_usage_id"), table_name="privacy_usage_badges")
    op.drop_table("privacy_usage_badges")
    op.drop_index(op.f("ix_privacy_usage_items_usage_id"), table_name="privacy_usage_items")
    op.drop_table("privacy_usage_items")
    op.drop_index(op.f("ix_privacy_usages_slug"), table_name="privacy_usages")
    op.drop_table("privacy_usages")
