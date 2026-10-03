"""blog cta

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blog_ctas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column("primary_label", sa.String(length=80), nullable=False),
        sa.Column("primary_href", sa.String(length=800), nullable=False),
        sa.Column("secondary_label", sa.String(length=80), nullable=False),
        sa.Column("secondary_href", sa.String(length=800), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blog_ctas")),
    )
    op.create_index(op.f("ix_blog_ctas_slug"), "blog_ctas", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_blog_ctas_slug"), table_name="blog_ctas")
    op.drop_table("blog_ctas")
