"""sustainability commitment cards

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sustainability_commitments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("kicker", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("subtitle", sa.String(length=400), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_commitments")),
    )
    op.create_index(
        op.f("ix_sustainability_commitments_slug"),
        "sustainability_commitments",
        ["slug"],
        unique=True,
    )
    op.create_table(
        "sustainability_commitment_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("commitment_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["commitment_id"],
            ["sustainability_commitments.id"],
            name=op.f(
                "fk_sustainability_commitment_items_commitment_id_sustainability_commitments"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_commitment_items")),
    )
    op.create_index(
        op.f("ix_sustainability_commitment_items_commitment_id"),
        "sustainability_commitment_items",
        ["commitment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sustainability_commitment_items_commitment_id"),
        table_name="sustainability_commitment_items",
    )
    op.drop_table("sustainability_commitment_items")
    op.drop_index(
        op.f("ix_sustainability_commitments_slug"), table_name="sustainability_commitments"
    )
    op.drop_table("sustainability_commitments")
