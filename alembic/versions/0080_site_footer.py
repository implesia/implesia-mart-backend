"""site footer config (one row, defaults served when absent)

Revision ID: 0080
Revises: 0079
Create Date: 2026-10-26

Creates `site_footer`, the admin-managed storefront footer (brand, description, logo,
address, copyright, display toggles, and ordered/enable-able link sections, trust points and
legal links).

Safe by construction:
 * Additive only: one new table. No existing table, column or row is touched.
 * No row is seeded. With no row the API serves the built-in defaults, which are the footer
   the storefront had before (see `app/services/site_footer_defaults.py`), so an empty
   table renders exactly the old footer and nothing is invented. The first admin save
   creates the row.
 * Every column has a server default, so a bare insert is valid.
 * Contact phone/email/WhatsApp and Facebook/LinkedIn stay in `contact_details` (single
   source); the footer only stores display toggles for them.

Rollback limits (downgrade): drops `site_footer`, so a footer an editor saved after
upgrading is lost and the storefront returns to the built-in defaults. Nothing else is
affected. Logos uploaded to media/footer stay on disk.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _text(name: str, length: int) -> sa.Column[str]:
    return sa.Column(name, sa.String(length=length), nullable=False, server_default="")


def _flag(name: str) -> sa.Column[bool]:
    return sa.Column(name, sa.Boolean(), nullable=False, server_default="true")


def _list(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
        nullable=False,
        server_default="[]",
    )


def upgrade() -> None:
    op.create_table(
        "site_footer",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        _text("brand_name", 80),
        _text("description", 400),
        _text("logo_src", 255),
        _text("logo_alt", 120),
        _text("address", 300),
        _text("copyright_text", 160),
        _flag("show_contact"),
        _flag("show_social"),
        _flag("show_whatsapp_cta"),
        _list("sections"),
        _list("trust_points"),
        _list("legal_links"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_footer")),
    )
    op.create_index(op.f("ix_site_footer_slug"), "site_footer", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_site_footer_slug"), table_name="site_footer")
    op.drop_table("site_footer")
