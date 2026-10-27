"""global search: trigram indexes for case-insensitive substring search

Revision ID: 0077
Revises: 0076
Create Date: 2026-10-26

Search runs `ILIKE '%word%'` on product, category and blog text. PostgreSQL can answer that
from a trigram GIN index (extension `pg_trgm`) instead of reading every row.

Safe by construction:
 * Indexes only. No table, column or row is created, changed or removed, so no backfill and
   no legacy data is touched.
 * The search endpoint is correct WITHOUT these indexes (same results, just a table scan on
   a small catalog). So if the database role may not create the extension, or the server has
   no pg_trgm, this migration logs that it skipped the indexes and succeeds.
 * Not PostgreSQL (SQLite in unit tests)? Nothing happens.
 * Index builds take a short write lock on the table. These tables are small. For a very
   large table run the CREATE INDEX statements below with CONCURRENTLY by hand instead.

Rollback limits (downgrade): drops only the indexes this migration created. It leaves the
`pg_trgm` extension installed (it may be used elsewhere); remove it by hand if you want to.
Nothing is lost, because indexes hold no data of their own.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

# (index name, table, column)
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_products_title_trgm", "products", "title"),
    ("ix_products_subtitle_trgm", "products", "subtitle"),
    ("ix_categories_name_trgm", "categories", "name"),
    ("ix_blog_posts_title_trgm", "blog_posts", "title"),
    ("ix_blog_posts_excerpt_trgm", "blog_posts", "excerpt"),
    ("ix_blog_post_blocks_text_trgm", "blog_post_blocks", "text"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except DBAPIError as exc:
        log.warning("pg_trgm is unavailable (%s); search will work without trigram indexes.", exc)
        return
    for name, table, column in INDEXES:
        bind.execute(
            sa.text(
                f'CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin ("{column}" gin_trgm_ops)'
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name, _table, _column in INDEXES:
        bind.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
