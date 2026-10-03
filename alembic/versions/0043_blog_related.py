"""blog related labels

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blog_related",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("toc_title", sa.String(length=120), nullable=False),
        sa.Column("products_title", sa.String(length=200), nullable=False),
        sa.Column("products_subtitle", sa.String(length=400), nullable=False),
        sa.Column("posts_title", sa.String(length=200), nullable=False),
        sa.Column("posts_subtitle", sa.String(length=200), nullable=False),
        sa.Column("posts_link_label", sa.String(length=80), nullable=False),
        sa.Column("coming_soon_label", sa.String(length=80), nullable=False),
        sa.Column("view_label", sa.String(length=80), nullable=False),
        sa.Column("details_label", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blog_related")),
    )
    op.create_index(op.f("ix_blog_related_slug"), "blog_related", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_blog_related_slug"), table_name="blog_related")
    op.drop_table("blog_related")
