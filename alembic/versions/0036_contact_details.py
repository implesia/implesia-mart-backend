"""contact details

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_details",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column("badge", sa.String(length=80), nullable=False),
        sa.Column("facebook_label", sa.String(length=80), nullable=False),
        sa.Column("facebook_href", sa.String(length=800), nullable=False),
        sa.Column("facebook_active", sa.Boolean(), nullable=False),
        sa.Column("linkedin_label", sa.String(length=80), nullable=False),
        sa.Column("linkedin_href", sa.String(length=800), nullable=False),
        sa.Column("linkedin_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_details")),
    )
    op.create_index(op.f("ix_contact_details_slug"), "contact_details", ["slug"], unique=True)
    op.create_table(
        "contact_detail_channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("details_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=160), nullable=False),
        sa.Column("href", sa.String(length=800), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["details_id"],
            ["contact_details.id"],
            name=op.f("fk_contact_detail_channels_details_id_contact_details"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_detail_channels")),
    )
    op.create_index(
        op.f("ix_contact_detail_channels_details_id"),
        "contact_detail_channels",
        ["details_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_contact_detail_channels_details_id"), table_name="contact_detail_channels"
    )
    op.drop_table("contact_detail_channels")
    op.drop_index(op.f("ix_contact_details_slug"), table_name="contact_details")
    op.drop_table("contact_details")
