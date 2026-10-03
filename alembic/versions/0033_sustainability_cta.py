"""sustainability cta

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sustainability_ctas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_ctas")),
    )
    op.create_index(
        op.f("ix_sustainability_ctas_slug"), "sustainability_ctas", ["slug"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sustainability_ctas_slug"), table_name="sustainability_ctas")
    op.drop_table("sustainability_ctas")
