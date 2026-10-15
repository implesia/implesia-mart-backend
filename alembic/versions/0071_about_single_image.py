"""about hero, story and dress blocks keep a single photo

Revision ID: 0071
Revises: 0070
Create Date: 2026-10-15

The storefront now shows one image per About section. Each owner keeps its first photo
by (sort_order, created_at) — exactly what the storefront renders — and every other photo
is moved, unchanged, into ``about_image_archive``. A unique index on the owner column then
enforces one photo per hero/story/dress. Downgrade restores archived rows with their
original ids and order. Media files are not touched.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0071"
down_revision: str | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (image table, owner column, owner table)
TABLES: tuple[tuple[str, str, str], ...] = (
    ("about_hero_images", "hero_id", "about_heroes"),
    ("about_story_images", "story_id", "about_story_blocks"),
    ("about_dress_images", "dress_id", "about_dress_blocks"),
)


def upgrade() -> None:
    op.create_table(
        "about_image_archive",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_table", sa.String(length=40), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("src", sa.String(length=255), nullable=False),
        sa.Column("alt", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_about_image_archive")),
    )
    op.create_index(
        op.f("ix_about_image_archive_source_table"), "about_image_archive", ["source_table"]
    )
    for table, owner, _owner_table in TABLES:
        ranked = f"""
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY {owner} ORDER BY sort_order, created_at, id
            ) AS rn
            FROM {table}
        """
        op.execute(
            f"""
            INSERT INTO about_image_archive
                (id, source_table, owner_id, src, alt, sort_order, created_at)
            SELECT t.id, '{table}', t.{owner}, t.src, t.alt, t.sort_order, t.created_at
            FROM {table} t JOIN ({ranked}) r ON r.id = t.id
            WHERE r.rn > 1
            """
        )
        op.execute(
            f"DELETE FROM {table} WHERE id IN "
            f"(SELECT id FROM about_image_archive WHERE source_table = '{table}')"
        )
        op.drop_index(f"ix_{table}_{owner}", table_name=table)
        op.create_index(f"ix_{table}_{owner}", table, [owner], unique=True)


def downgrade() -> None:
    for table, owner, owner_table in TABLES:
        op.drop_index(f"ix_{table}_{owner}", table_name=table)
        op.create_index(f"ix_{table}_{owner}", table, [owner], unique=False)
        # Only restore photos whose owner still exists (a block may have been deleted since).
        op.execute(
            f"""
            INSERT INTO {table} (id, {owner}, src, alt, sort_order, created_at, updated_at)
            SELECT a.id, a.owner_id, a.src, a.alt, a.sort_order, a.created_at, now()
            FROM about_image_archive a
            WHERE a.source_table = '{table}'
              AND EXISTS (SELECT 1 FROM {owner_table} o WHERE o.id = a.owner_id)
            """
        )
    op.drop_index(op.f("ix_about_image_archive_source_table"), table_name="about_image_archive")
    op.drop_table("about_image_archive")
