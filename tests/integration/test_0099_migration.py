"""Migration 0099 adds nullable site SEO columns and leaves other tables alone."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.helpers import SEED_CATEGORY_ID

pytestmark = pytest.mark.postgres

MIGRATION = Path(__file__).parents[2] / "alembic" / "versions" / "0099_site_seo_settings.py"


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0099", MIGRATION)
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


async def _tables(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    return {row[0] for row in rows}


async def _seo_columns(db: AsyncSession) -> dict[str, tuple[int | None, str]]:
    rows = await db.execute(
        text(
            "SELECT column_name, character_maximum_length, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'site_settings'"
        )
    )
    return {row[0]: (row[1], row[2]) for row in rows}


async def test_0099_adds_nullable_seo_settings_and_leaves_categories(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        module = _migration()
        assert module.revision == "0099"
        assert module.down_revision == "0098"
        assert "site_settings" in await _tables(db)
        columns = await _seo_columns(db)
        assert columns["seo_title"] == (70, "YES")
        assert columns["seo_description"] == (170, "YES")
        assert columns["seo_title_template"] == (80, "YES")
        assert columns["slug"][1] == "NO"
        name = (
            await db.execute(
                text("SELECT name FROM categories WHERE id = :id"),
                {"id": SEED_CATEGORY_ID},
            )
        ).scalar_one()
        assert name == "Fashion"

    try:
        async with pg() as db:
            await _run(db, "downgrade")
            tables = await _tables(db)
            assert "site_settings" not in tables
            assert "categories" in tables
            assert "orders" in tables
            assert "products" in tables
            still = (
                await db.execute(
                    text("SELECT name FROM categories WHERE id = :id"),
                    {"id": SEED_CATEGORY_ID},
                )
            ).scalar_one()
            assert still == "Fashion"
            await _run(db, "upgrade")
            columns = await _seo_columns(db)
            assert columns["seo_title"] == (70, "YES")
            assert columns["seo_description"] == (170, "YES")
            assert columns["seo_title_template"] == (80, "YES")
            count = (await db.execute(text("SELECT count(*) FROM site_settings"))).scalar_one()
            assert count == 0
            kept = (
                await db.execute(
                    text("SELECT name FROM categories WHERE id = :id"),
                    {"id": SEED_CATEGORY_ID},
                )
            ).scalar_one()
            assert kept == "Fashion"
    finally:
        async with pg() as db:
            if "site_settings" not in await _tables(db):
                await _run(db, "upgrade")
