"""about page mission and vision

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "about_mission_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_mission_sections")),
    )
    op.create_index(
        op.f("ix_about_mission_sections_slug"),
        "about_mission_sections",
        ["slug"],
        unique=True,
    )
    op.create_table(
        "about_mission_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("card_key", sa.String(length=20), nullable=False),
        sa.Column("icon", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=800), nullable=False),
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
            ["about_mission_sections.id"],
            name=op.f("fk_about_mission_cards_section_id_about_mission_sections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_mission_cards")),
        sa.UniqueConstraint("section_id", "card_key", name="uq_about_mission_card_key"),
    )
    op.create_index(
        op.f("ix_about_mission_cards_section_id"),
        "about_mission_cards",
        ["section_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_about_mission_cards_section_id"), table_name="about_mission_cards")
    op.drop_table("about_mission_cards")
    op.drop_index(op.f("ix_about_mission_sections_slug"), table_name="about_mission_sections")
    op.drop_table("about_mission_sections")
