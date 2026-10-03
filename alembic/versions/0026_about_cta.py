"""about page closing call to action

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "about_cta",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_cta")),
    )
    op.create_index(op.f("ix_about_cta_slug"), "about_cta", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_about_cta_slug"), table_name="about_cta")
    op.drop_table("about_cta")
