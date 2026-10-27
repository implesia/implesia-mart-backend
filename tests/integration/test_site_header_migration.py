"""Migration 0082 on real PostgreSQL: creates the table with safe defaults, and rolls back."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services import site_header_service
from app.services.site_header_defaults import DEFAULT_ITEMS

pytestmark = pytest.mark.postgres

MIGRATION = Path(__file__).parents[2] / "alembic" / "versions" / "0082_site_header.py"


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0082", MIGRATION)
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


async def _exists(db: AsyncSession) -> bool:
    row = await db.execute(text("SELECT to_regclass('public.site_header')"))
    return row.scalar_one() is not None


async def test_0082_creates_the_table_serves_defaults_and_rolls_back(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        await _run(db, "downgrade")  # the suite schema is the new one
        assert not await _exists(db)
        await _run(db, "upgrade")
        assert await _exists(db)
        assert (await db.execute(text("SELECT count(*) FROM site_header"))).scalar_one() == 0
        live = await site_header_service.public_view(db)  # empty table: the previous menu
        assert [item.href for item in live.items] == [i["href"] for i in DEFAULT_ITEMS]

        # Column defaults make a bare insert valid and still render the defaults.
        await db.execute(text("INSERT INTO site_header (id, slug) VALUES (gen_random_uuid(), 'x')"))
        await db.commit()
        row = (await db.execute(text("SELECT items::text FROM site_header"))).one()
        assert tuple(row) == ("[]",)
        await db.execute(text("DELETE FROM site_header"))
        await db.commit()
        await _run(db, "downgrade")
        assert not await _exists(db)
        await _run(db, "upgrade")
        assert await _exists(db)
