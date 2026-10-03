"""faq listing

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "faq_listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("count_suffix", sa.String(length=80), nullable=False),
        sa.Column("empty_title", sa.String(length=200), nullable=False),
        sa.Column("empty_body", sa.String(length=800), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_listings")),
    )
    op.create_index(op.f("ix_faq_listings_slug"), "faq_listings", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_faq_listings_slug"), table_name="faq_listings")
    op.drop_table("faq_listings")
