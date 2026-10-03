"""sustainability origin

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sustainability_origins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("eyebrow", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=800), nullable=False),
        sa.Column("quote", sa.String(length=400), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_origins")),
    )
    op.create_index(
        op.f("ix_sustainability_origins_slug"), "sustainability_origins", ["slug"], unique=True
    )
    op.create_table(
        "sustainability_origin_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("origin_id", sa.Uuid(), nullable=False),
        sa.Column("src", sa.String(length=255), nullable=False),
        sa.Column("alt", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["origin_id"],
            ["sustainability_origins.id"],
            name=op.f("fk_sustainability_origin_images_origin_id_sustainability_origins"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sustainability_origin_images")),
    )
    op.create_index(
        op.f("ix_sustainability_origin_images_origin_id"),
        "sustainability_origin_images",
        ["origin_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sustainability_origin_images_origin_id"),
        table_name="sustainability_origin_images",
    )
    op.drop_table("sustainability_origin_images")
    op.drop_index(op.f("ix_sustainability_origins_slug"), table_name="sustainability_origins")
    op.drop_table("sustainability_origins")
