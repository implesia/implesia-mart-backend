"""Storefront header logo

Revision ID: 0100
Revises: 0099
Create Date: 2026-11-20

Adds `logo_src` and `logo_alt` to `site_header`, so an editor can upload the logo shown in the
storefront navbar. Both columns default to an empty string, so every existing row (and the
built-in menu when no row exists) keeps showing the built-in logo.

Downgrade drops the two columns; a logo path saved after upgrading is lost (the uploaded file
stays on disk but is no longer referenced).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0100"
down_revision: str | None = "0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "site_header",
        sa.Column("logo_src", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "site_header",
        sa.Column("logo_alt", sa.String(length=120), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("site_header", "logo_alt")
    op.drop_column("site_header", "logo_src")
