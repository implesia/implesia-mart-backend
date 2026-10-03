"""about page stats

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "about_stats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_stats")),
    )
    op.create_index(op.f("ix_about_stats_slug"), "about_stats", ["slug"], unique=True)
    op.create_table(
        "about_stat_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("stats_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=40), nullable=False),
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
            ["stats_id"],
            ["about_stats.id"],
            name=op.f("fk_about_stat_items_stats_id_about_stats"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_stat_items")),
    )
    op.create_index(
        op.f("ix_about_stat_items_stats_id"),
        "about_stat_items",
        ["stats_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_about_stat_items_stats_id"), table_name="about_stat_items")
    op.drop_table("about_stat_items")
    op.drop_index(op.f("ix_about_stats_slug"), table_name="about_stats")
    op.drop_table("about_stats")
