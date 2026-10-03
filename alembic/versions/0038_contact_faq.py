"""contact faq

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_faqs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_faqs")),
    )
    op.create_index(op.f("ix_contact_faqs_slug"), "contact_faqs", ["slug"], unique=True)
    op.create_table(
        "contact_faq_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("faq_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.String(length=200), nullable=False),
        sa.Column("answer", sa.String(length=800), nullable=False),
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
            ["contact_faqs.id"],
            name=op.f("fk_contact_faq_items_faq_id_contact_faqs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_faq_items")),
    )
    op.create_index(
        op.f("ix_contact_faq_items_faq_id"),
        "contact_faq_items",
        ["faq_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_contact_faq_items_faq_id"), table_name="contact_faq_items")
    op.drop_table("contact_faq_items")
    op.drop_index(op.f("ix_contact_faqs_slug"), table_name="contact_faqs")
    op.drop_table("contact_faqs")
