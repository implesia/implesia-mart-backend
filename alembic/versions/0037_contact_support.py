"""contact support

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "contact_supports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_supports")),
    )
    op.create_index(op.f("ix_contact_supports_slug"), "contact_supports", ["slug"], unique=True)
    op.create_table(
        "contact_support_hours",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("support_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["support_id"],
            ["contact_supports.id"],
            name=op.f("fk_contact_support_hours_support_id_contact_supports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_support_hours")),
    )
    op.create_index(
        op.f("ix_contact_support_hours_support_id"),
        "contact_support_hours",
        ["support_id"],
        unique=False,
    )
    op.create_table(
        "contact_support_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("support_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("href", sa.String(length=800), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["support_id"],
            ["contact_supports.id"],
            name=op.f("fk_contact_support_links_support_id_contact_supports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_support_links")),
    )
    op.create_index(
        op.f("ix_contact_support_links_support_id"),
        "contact_support_links",
        ["support_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_contact_support_links_support_id"), table_name="contact_support_links"
    )
    op.drop_table("contact_support_links")
    op.drop_index(
        op.f("ix_contact_support_hours_support_id"), table_name="contact_support_hours"
    )
    op.drop_table("contact_support_hours")
    op.drop_index(op.f("ix_contact_supports_slug"), table_name="contact_supports")
    op.drop_table("contact_supports")
