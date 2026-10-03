"""about page custom dresses

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "about_dress_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_dress_sections")),
    )
    op.create_index(
        op.f("ix_about_dress_sections_slug"), "about_dress_sections", ["slug"], unique=True
    )
    op.create_table(
        "about_dress_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("kicker", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subtitle", sa.String(length=800), nullable=False),
        sa.Column("primary_label", sa.String(length=80), nullable=False),
        sa.Column("primary_href", sa.String(length=800), nullable=False),
        sa.Column("secondary_label", sa.String(length=80), nullable=False),
        sa.Column("secondary_href", sa.String(length=800), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["about_dress_sections.id"],
            name=op.f("fk_about_dress_blocks_section_id_about_dress_sections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_dress_blocks")),
    )
    op.create_index(
        op.f("ix_about_dress_blocks_section_id"),
        "about_dress_blocks",
        ["section_id"],
        unique=False,
    )
    op.create_table(
        "about_dress_features",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dress_id", sa.Uuid(), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["dress_id"],
            ["about_dress_blocks.id"],
            name=op.f("fk_about_dress_features_dress_id_about_dress_blocks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_dress_features")),
    )
    op.create_index(
        op.f("ix_about_dress_features_dress_id"),
        "about_dress_features",
        ["dress_id"],
        unique=False,
    )
    op.create_table(
        "about_dress_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dress_id", sa.Uuid(), nullable=False),
        sa.Column("src", sa.String(length=255), nullable=False),
        sa.Column("alt", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["dress_id"],
            ["about_dress_blocks.id"],
            name=op.f("fk_about_dress_images_dress_id_about_dress_blocks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_dress_images")),
    )
    op.create_index(
        op.f("ix_about_dress_images_dress_id"),
        "about_dress_images",
        ["dress_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_about_dress_images_dress_id"), table_name="about_dress_images")
    op.drop_table("about_dress_images")
    op.drop_index(op.f("ix_about_dress_features_dress_id"), table_name="about_dress_features")
    op.drop_table("about_dress_features")
    op.drop_index(op.f("ix_about_dress_blocks_section_id"), table_name="about_dress_blocks")
    op.drop_table("about_dress_blocks")
    op.drop_index(op.f("ix_about_dress_sections_slug"), table_name="about_dress_sections")
    op.drop_table("about_dress_sections")
