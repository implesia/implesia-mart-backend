"""Migration 0078 on real PostgreSQL: backfill, data preservation, and the rollback."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.blogs import posts_service

pytestmark = pytest.mark.postgres

MIGRATION = Path(__file__).parents[2] / "alembic" / "versions" / "0078_blog_seo_fields.py"
BLOB = "blob:http://localhost:3000/legacy-cover"


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0078", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(db: AsyncSession, direction: str) -> None:
    module = _migration()

    def go(sync_conn) -> None:  # type: ignore[no-untyped-def]
        with Operations.context(MigrationContext.configure(sync_conn)):
            getattr(module, direction)()

    conn = await db.connection()
    await conn.run_sync(go)
    await db.commit()


async def _columns(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'blog_posts' AND column_name LIKE 'seo\\_%'"
        )
    )
    return {row[0] for row in rows}


async def test_0078_backfills_legacy_rows_and_rolls_back(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        await _run(db, "downgrade")  # the suite schema is the new one; go back to 0077's shape
        assert await _columns(db) == set()
        await db.execute(
            text(
                "INSERT INTO blog_posts (id, slug, title, excerpt, cover_image, is_active, "
                "sort_order, tags, related_product_slugs, cover_alt, author, author_role, "
                "published_at, read_time, created_at, updated_at) "
                "SELECT gen_random_uuid(), 'legacy', 'Legacy post', 'x', :cover, true, 0, "
                "'[]'::json, '[]'::json, '', 'Team', '', '3 Oct 2026', '', now(), now()"
            ),
            {"cover": BLOB},
        )
        await db.commit()

    try:
        async with pg() as db:
            await _run(db, "upgrade")
            assert await _columns(db) == {"seo_title", "seo_description"}
            row = (
                await db.execute(
                    text("SELECT title, cover_image, seo_title, seo_description FROM blog_posts")
                )
            ).one()
            assert tuple(row) == ("Legacy post", BLOB, "", "")

        async with pg() as db:
            post = await posts_service.public_by_slug(db, "legacy")
            assert post.cover_image == ""  # public read hides the unusable value
            stored = (await db.execute(text("SELECT cover_image FROM blog_posts"))).scalar_one()
            assert stored == BLOB  # but the stored value is untouched
    finally:
        async with pg() as db:
            if await _columns(db) != {"seo_title", "seo_description"}:
                await _run(db, "upgrade")
