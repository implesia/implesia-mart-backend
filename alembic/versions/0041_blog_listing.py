"""blog listing

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blog_listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("heading", sa.String(length=200), nullable=False),
        sa.Column("all_label", sa.String(length=80), nullable=False),
        sa.Column("count_suffix", sa.String(length=80), nullable=False),
        sa.Column("empty_message", sa.String(length=400), nullable=False),
        sa.Column("featured_label", sa.String(length=80), nullable=False),
        sa.Column("read_label", sa.String(length=80), nullable=False),
        sa.Column("read_suffix", sa.String(length=80), nullable=False),
        sa.Column("tabs_label", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blog_listings")),
    )
    op.create_index(op.f("ix_blog_listings_slug"), "blog_listings", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_blog_listings_slug"), table_name="blog_listings")
    op.drop_table("blog_listings")
