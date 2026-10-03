"""home faq questions

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "home_faqs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("kicker", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column("more_label", sa.String(length=80), nullable=False),
        sa.Column("more_href", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_faqs")),
    )
    op.create_index(op.f("ix_home_faqs_slug"), "home_faqs", ["slug"], unique=True)
    op.create_table(
        "home_faq_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("faq_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("question", sa.String(length=240), nullable=False),
        sa.Column("answer", sa.String(length=2000), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["faq_id"],
            ["home_faqs.id"],
            name=op.f("fk_home_faq_items_faq_id_home_faqs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_home_faq_items")),
    )
    op.create_index(
        op.f("ix_home_faq_items_faq_id"),
        "home_faq_items",
        ["faq_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_home_faq_items_faq_id"), table_name="home_faq_items")
    op.drop_table("home_faq_items")
    op.drop_index(op.f("ix_home_faqs_slug"), table_name="home_faqs")
    op.drop_table("home_faqs")
