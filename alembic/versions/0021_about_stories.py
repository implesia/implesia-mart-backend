"""about page stories

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "about_story_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_story_sections")),
    )
    op.create_index(
        op.f("ix_about_story_sections_slug"), "about_story_sections", ["slug"], unique=True
    )
    op.create_table(
        "about_story_blocks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("kicker", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("cta_label", sa.String(length=80), nullable=False),
        sa.Column("cta_href", sa.String(length=500), nullable=False),
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
            ["about_story_sections.id"],
            name=op.f("fk_about_story_blocks_section_id_about_story_sections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_story_blocks")),
    )
    op.create_index(
        op.f("ix_about_story_blocks_section_id"),
        "about_story_blocks",
        ["section_id"],
        unique=False,
    )
    op.create_table(
        "about_story_paragraphs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.String(length=2000), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["story_id"],
            ["about_story_blocks.id"],
            name=op.f("fk_about_story_paragraphs_story_id_about_story_blocks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_story_paragraphs")),
    )
    op.create_index(
        op.f("ix_about_story_paragraphs_story_id"),
        "about_story_paragraphs",
        ["story_id"],
        unique=False,
    )
    op.create_table(
        "about_story_images",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("story_id", sa.Uuid(), nullable=False),
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
            ["story_id"],
            ["about_story_blocks.id"],
            name=op.f("fk_about_story_images_story_id_about_story_blocks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_story_images")),
    )
    op.create_index(
        op.f("ix_about_story_images_story_id"),
        "about_story_images",
        ["story_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_about_story_images_story_id"), table_name="about_story_images")
    op.drop_table("about_story_images")
    op.drop_index(op.f("ix_about_story_paragraphs_story_id"), table_name="about_story_paragraphs")
    op.drop_table("about_story_paragraphs")
    op.drop_index(op.f("ix_about_story_blocks_section_id"), table_name="about_story_blocks")
    op.drop_table("about_story_blocks")
    op.drop_index(op.f("ix_about_story_sections_slug"), table_name="about_story_sections")
    op.drop_table("about_story_sections")
