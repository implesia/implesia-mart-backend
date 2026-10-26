"""Search against real PostgreSQL: ILIKE semantics, Bangla text, JSON tags, trigram indexes."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.blogs.posts import BlogPost, BlogPostBlock
from app.schemas.search import SearchQuery
from app.services import search_service
from tests.integration.helpers import product

pytestmark = pytest.mark.postgres

MIGRATION = Path(__file__).parents[2] / "alembic" / "versions" / "0077_search_indexes.py"


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0077", MIGRATION)
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


async def _index_names(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        text("SELECT indexname FROM pg_indexes WHERE indexname LIKE '%\\_trgm'")
    )
    return {row[0] for row in rows}


async def _seed(pg: async_sessionmaker[AsyncSession]) -> None:
    async with pg() as db:
        first = product()
        first.title = "লাল সুতি শার্ট"
        second = product()
        second.title = "Fifty% Off Lamp"
        third = product()
        third.title = "Plain lamp"
        third.subtitle = "red shade"
        hidden = product()
        hidden.title = "Hidden lamp"
        hidden.published = False
        db.add_all([first, second, third, hidden])
        post = BlogPost(slug="bangla-guide", title="গাইড", excerpt="", tags=["চার্জার", "battery"])
        post.blocks = [
            BlogPostBlock(block_type="paragraph", text="Visible body", sort_order=0),
            BlogPostBlock(
                block_type="paragraph", text="Secret body", is_active=False, sort_order=1
            ),
        ]
        db.add(post)
        db.add(BlogPost(slug="draft", title="Draft lamp", is_active=False))
        await db.commit()


async def _find(db: AsyncSession, q: str, kind: str = "all") -> tuple[list[str], list[str]]:
    result = await search_service.search(db, SearchQuery(q=q, type=kind))
    return [i.title for i in result.products.items], [i.title for i in result.blogs.items]


async def test_search_semantics_on_postgres(pg: async_sessionmaker[AsyncSession]) -> None:
    await _seed(pg)
    async with pg() as db:
        assert (await _find(db, "শার্ট"))[0] == ["লাল সুতি শার্ট"]
        assert sorted((await _find(db, "LAMP"))[0]) == ["Fifty% Off Lamp", "Plain lamp"]
        assert (await _find(db, "plain%lamp"))[0] == []
        assert (await _find(db, "pl_in"))[0] == []
        assert (await _find(db, "'; DROP TABLE products; --"))[0] == []
        assert (await _find(db, "lamp red"))[0] == ["Plain lamp"]  # title + subtitle, any column
        assert "Hidden lamp" not in (await _find(db, "lamp"))[0]
        assert (await _find(db, "lamp"))[1] == []  # the only matching post is inactive
        assert (await _find(db, "চার্জার"))[1] == ["গাইড"]  # Bangla tag inside a JSON column
        assert (await _find(db, "battery"))[1] == ["গাইড"]
        assert (await _find(db, "visible body"))[1] == ["গাইড"]
        assert (await _find(db, "secret"))[1] == []


async def test_trigram_migration_up_down_up_is_idempotent_and_used(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    await _seed(pg)
    async with pg() as db:
        await _run(db, "downgrade")
        assert await _index_names(db) == set()
        await _run(db, "upgrade")
        created = await _index_names(db)
        assert len(created) == 6
        await _run(db, "upgrade")  # running it again changes nothing
        assert await _index_names(db) == created
        assert (await _find(db, "শার্ট"))[0] == ["লাল সুতি শার্ট"]  # same answer with indexes
        await db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in await db.execute(
                text("EXPLAIN SELECT id FROM products WHERE title ILIKE '%lamp%'")
            )
        )
        assert "ix_products_title_trgm" in plan
        await db.rollback()
        await _run(db, "downgrade")
        assert await _index_names(db) == set()
        assert (await db.scalar(text("SELECT count(*) FROM products"))) == 4  # no data touched
        await _run(db, "upgrade")
