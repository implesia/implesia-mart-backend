"""contact form

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_forms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column("cta", sa.String(length=80), nullable=False),
        sa.Column("hint", sa.String(length=200), nullable=False),
        sa.Column("name_label", sa.String(length=80), nullable=False),
        sa.Column("name_placeholder", sa.String(length=160), nullable=False),
        sa.Column("phone_label", sa.String(length=80), nullable=False),
        sa.Column("phone_placeholder", sa.String(length=160), nullable=False),
        sa.Column("subject_label", sa.String(length=80), nullable=False),
        sa.Column("subject_placeholder", sa.String(length=160), nullable=False),
        sa.Column("message_label", sa.String(length=80), nullable=False),
        sa.Column("message_placeholder", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_forms")),
    )
    op.create_index(op.f("ix_contact_forms_slug"), "contact_forms", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_contact_forms_slug"), table_name="contact_forms")
    op.drop_table("contact_forms")
