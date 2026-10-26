"""site header menu (one row, built-in menu served when absent)

Revision ID: 0082
Revises: 0081
Create Date: 2026-10-26

Creates `site_header`, the admin-managed storefront top navigation (one ordered list of
label / link / enabled).

Safe by construction:
 * Additive only: one new table. No existing table, column or row is touched.
 * No row is seeded. With no row the API serves the built-in menu, which is the navigation
   the storefront had before (see `app/services/site_header_defaults.py`), so an empty table
   renders exactly the old menu. The first admin save creates the row.
 * Every column has a server default, so a bare insert is valid.

Rollback limits (downgrade): drops `site_header`, so a menu an editor saved after upgrading
is lost and the storefront returns to the built-in menu. Nothing else is affected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0082"
down_revision: str | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_header",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column(
            "items",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_header")),
    )
    op.create_index(op.f("ix_site_header_slug"), "site_header", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_site_header_slug"), table_name="site_header")
    op.drop_table("site_header")
