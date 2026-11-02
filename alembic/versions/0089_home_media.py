"""home media section (image, uploaded video or YouTube; one row, hidden by default)

Revision ID: 0089
Revises: 0088
Create Date: 2026-11-02

Creates `home_media`, the content-managed video/media section shown directly above the
customer testimonials on the home page.

Safe by construction:
 * Additive only: one new table. No existing table, column or row is touched.
 * No row is seeded. With no row the public endpoint returns null and the storefront shows
   no section, so nothing changes until an editor publishes one.
 * Every column has a server default (is_active false, media_type image, cta_enabled false).

Rollback limits (downgrade): drops `home_media`, so a section an editor configured after
upgrading is lost. Nothing else is affected. Files uploaded to media/home-media stay on disk.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _text(name: str, length: int) -> sa.Column[str]:
    return sa.Column(name, sa.String(length=length), nullable=False, server_default="")


def upgrade() -> None:
    op.create_table(
        "home_media",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        _text("heading", 120),
        _text("subheading", 240),
        sa.Column("media_type", sa.String(length=10), nullable=False, server_default="image"),
        _text("image_src", 255),
        _text("video_src", 255),
        _text("youtube_id", 20),
        _text("thumbnail_src", 255),
        _text("media_alt", 200),
        _text("description", 500),
        sa.Column("cta_enabled", sa.Boolean(), nullable=False, server_default="false"),
        _text("cta_label", 60),
        _text("cta_href", 255),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_media")),
    )
    op.create_index(op.f("ix_home_media_slug"), "home_media", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_home_media_slug"), table_name="home_media")
    op.drop_table("home_media")
