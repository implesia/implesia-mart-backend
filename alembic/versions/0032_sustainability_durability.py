"""sustainability durability

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sustainability_durabilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=800), nullable=False),
        sa.Column("image_src", sa.String(length=255), nullable=False),
        sa.Column("image_alt", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_durabilities")),
    )
    op.create_index(
        op.f("ix_sustainability_durabilities_slug"),
        "sustainability_durabilities",
        ["slug"],
        unique=True,
    )
    op.create_table(
        "sustainability_durability_bullets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("durability_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["durability_id"],
            ["sustainability_durabilities.id"],
            name=op.f(
                "fk_sustainability_durability_bullets_durability_id_sustainability_durabilities"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_durability_bullets")),
    )
    op.create_index(
        op.f("ix_sustainability_durability_bullets_durability_id"),
        "sustainability_durability_bullets",
        ["durability_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sustainability_durability_bullets_durability_id"),
        table_name="sustainability_durability_bullets",
    )
    op.drop_table("sustainability_durability_bullets")
    op.drop_index(
        op.f("ix_sustainability_durabilities_slug"), table_name="sustainability_durabilities"
    )
    op.drop_table("sustainability_durabilities")
