"""faq callout

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "faq_callouts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("eyebrow", sa.String(length=80), nullable=False),
        sa.Column("body", sa.String(length=800), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_callouts")),
    )
    op.create_index(op.f("ix_faq_callouts_slug"), "faq_callouts", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_faq_callouts_slug"), table_name="faq_callouts")
    op.drop_table("faq_callouts")
