"""home newsletter perks

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_newsletters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("eyebrow", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column("placeholder", sa.String(length=80), nullable=False),
        sa.Column("cta", sa.String(length=40), nullable=False),
        sa.Column("success", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_newsletters")),
    )
    op.create_index(op.f("ix_home_newsletters_slug"), "home_newsletters", ["slug"], unique=True)
    op.create_table(
        "home_newsletter_perks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("newsletter_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["newsletter_id"],
            ["home_newsletters.id"],
            name=op.f("fk_home_newsletter_perks_newsletter_id_home_newsletters"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_newsletter_perks")),
    )
    op.create_index(
        op.f("ix_home_newsletter_perks_newsletter_id"),
        "home_newsletter_perks",
        ["newsletter_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_home_newsletter_perks_newsletter_id"), table_name="home_newsletter_perks"
    )
    op.drop_table("home_newsletter_perks")
    op.drop_index(op.f("ix_home_newsletters_slug"), table_name="home_newsletters")
    op.drop_table("home_newsletters")
