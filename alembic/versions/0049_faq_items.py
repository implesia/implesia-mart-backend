"""faq items

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "faq_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
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
            ["category_id"],
            ["faq_category_items.id"],
            name=op.f("fk_faq_questions_category_id_faq_category_items"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_faq_questions")),
    )
    op.create_index(op.f("ix_faq_questions_category_id"), "faq_questions", ["category_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_faq_questions_category_id"), table_name="faq_questions")
    op.drop_table("faq_questions")
