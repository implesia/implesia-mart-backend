"""Storefront default SEO settings

Revision ID: 0099
Revises: 0098
Create Date: 2026-11-16

Creates `site_settings`, one row (slug "main") for the storefront home/default
title, meta description, and optional title template.

The three SEO columns are nullable. No row is seeded and no existing row is
updated. An empty table means the storefront keeps its built-in copy.

Downgrade drops only `site_settings`. A title an editor saved after upgrading
is removed with the table. Other tables are left alone.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0099"
down_revision: str | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("seo_title", sa.String(length=70), nullable=True),
        sa.Column("seo_description", sa.String(length=170), nullable=True),
        sa.Column("seo_title_template", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_settings")),
    )
    op.create_index(op.f("ix_site_settings_slug"), "site_settings", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_site_settings_slug"), table_name="site_settings")
    op.drop_table("site_settings")
