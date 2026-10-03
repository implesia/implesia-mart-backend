"""faq hero

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "faq_heroes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("eyebrow", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column("placeholder", sa.String(length=200), nullable=False),
        sa.Column("search_label", sa.String(length=80), nullable=False),
        sa.Column("clear_label", sa.String(length=80), nullable=False),
        sa.Column("trending_label", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_heroes")),
    )
    op.create_index(op.f("ix_faq_heroes_slug"), "faq_heroes", ["slug"], unique=True)
    op.create_table(
        "faq_hero_searches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hero_id", sa.Uuid(), nullable=False),
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
            ["hero_id"],
            ["faq_heroes.id"],
            name=op.f("fk_faq_hero_searches_hero_id_faq_heroes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_hero_searches")),
    )
    op.create_index(
        op.f("ix_faq_hero_searches_hero_id"),
        "faq_hero_searches",
        ["hero_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_faq_hero_searches_hero_id"), table_name="faq_hero_searches")
    op.drop_table("faq_hero_searches")
    op.drop_index(op.f("ix_faq_heroes_slug"), table_name="faq_heroes")
    op.drop_table("faq_heroes")
