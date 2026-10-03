"""sustainability impact stats

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sustainability_impacts",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_impacts")),
    )
    op.create_index(
        op.f("ix_sustainability_impacts_slug"), "sustainability_impacts", ["slug"], unique=True
    )
    op.create_table(
        "sustainability_impact_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("impact_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=40), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["impact_id"],
            ["sustainability_impacts.id"],
            name=op.f("fk_sustainability_impact_items_impact_id_sustainability_impacts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_impact_items")),
    )
    op.create_index(
        op.f("ix_sustainability_impact_items_impact_id"),
        "sustainability_impact_items",
        ["impact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sustainability_impact_items_impact_id"),
        table_name="sustainability_impact_items",
    )
    op.drop_table("sustainability_impact_items")
    op.drop_index(op.f("ix_sustainability_impacts_slug"), table_name="sustainability_impacts")
    op.drop_table("sustainability_impacts")
