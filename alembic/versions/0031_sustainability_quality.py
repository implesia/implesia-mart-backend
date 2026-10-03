"""sustainability quality

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sustainability_qualities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=800), nullable=False),
        sa.Column("image_src", sa.String(length=255), nullable=False),
        sa.Column("image_alt", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_qualities")),
    )
    op.create_index(
        op.f("ix_sustainability_qualities_slug"), "sustainability_qualities", ["slug"], unique=True
    )
    op.create_table(
        "sustainability_quality_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quality_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["quality_id"],
            ["sustainability_qualities.id"],
            name=op.f("fk_sustainability_quality_steps_quality_id_sustainability_qualities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_quality_steps")),
    )
    op.create_index(
        op.f("ix_sustainability_quality_steps_quality_id"),
        "sustainability_quality_steps",
        ["quality_id"],
        unique=False,
    )
    op.create_table(
        "sustainability_quality_badges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quality_id", sa.Uuid(), nullable=False),
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
            ["quality_id"],
            ["sustainability_qualities.id"],
            name=op.f("fk_sustainability_quality_badges_quality_id_sustainability_qualities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_quality_badges")),
    )
    op.create_index(
        op.f("ix_sustainability_quality_badges_quality_id"),
        "sustainability_quality_badges",
        ["quality_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sustainability_quality_badges_quality_id"),
        table_name="sustainability_quality_badges",
    )
    op.drop_table("sustainability_quality_badges")
    op.drop_index(
        op.f("ix_sustainability_quality_steps_quality_id"),
        table_name="sustainability_quality_steps",
    )
    op.drop_table("sustainability_quality_steps")
    op.drop_index(op.f("ix_sustainability_qualities_slug"), table_name="sustainability_qualities")
    op.drop_table("sustainability_qualities")
