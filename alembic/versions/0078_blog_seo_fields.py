"""blog posts: SEO title and description

Revision ID: 0078
Revises: 0077
Create Date: 2026-10-26

Adds `seo_title` (70) and `seo_description` (200) to `blog_posts`.

Safe by construction:
 * Additive only. Both columns are NOT NULL with a server default of '' so every existing
   article is backfilled with an empty value by the database itself. The public pages fall
   back to the article title and excerpt when these are empty, so nothing changes visually
   until an editor fills them in.
 * No existing column or row is rewritten. Legacy covers (including broken `blob:` values)
   are left exactly as stored; the API hides unusable ones when it reads them.
 * Adding a column with a constant default is a metadata-only change on PostgreSQL 11+.

Rollback limits (downgrade): drops the two columns, so any SEO text entered after upgrading
is lost. Nothing else is affected. Files uploaded to media/blogs stay on disk.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "blog_posts",
        sa.Column("seo_title", sa.String(length=70), nullable=False, server_default=""),
    )
    op.add_column(
        "blog_posts",
        sa.Column("seo_description", sa.String(length=200), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("blog_posts", "seo_description")
    op.drop_column("blog_posts", "seo_title")
