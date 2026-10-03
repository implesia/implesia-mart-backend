"""privacy introduction

Revision ID: 0061
Revises: 0060
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0061"
down_revision: str | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "privacy_intros",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("nav_label", sa.String(length=80), nullable=False),
        sa.Column("heading", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_intros")),
    )
    op.create_index(op.f("ix_privacy_intros_slug"), "privacy_intros", ["slug"], unique=True)
    op.create_table(
        "privacy_intro_paragraphs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("intro_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(length=800), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["intro_id"],
            ["privacy_intros.id"],
            name="fk_privacy_intro_paragraphs_intro_id_privacy_intros",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_intro_paragraphs")),
    )
    op.create_index(
        op.f("ix_privacy_intro_paragraphs_intro_id"),
        "privacy_intro_paragraphs",
        ["intro_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_privacy_intro_paragraphs_intro_id"), table_name="privacy_intro_paragraphs"
    )
    op.drop_table("privacy_intro_paragraphs")
    op.drop_index(op.f("ix_privacy_intros_slug"), table_name="privacy_intros")
    op.drop_table("privacy_intros")
