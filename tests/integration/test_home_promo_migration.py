"""Migration 0079 on real PostgreSQL: creates the table with safe defaults, and rolls back."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.home import promo_service

pytestmark = pytest.mark.postgres

MIGRATION = Path(__file__).parents[2] / "alembic" / "versions" / "0079_home_promo.py"


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0079", MIGRATION)
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
    row = await db.execute(text("SELECT to_regclass('public.home_promo')"))
    return row.scalar_one() is not None


async def test_0079_creates_a_hidden_table_and_rolls_back(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    async with pg() as db:
        await _run(db, "downgrade")  # the suite schema is the new one
        assert not await _exists(db)
        await _run(db, "upgrade")
        assert await _exists(db)
        assert (await db.execute(text("SELECT count(*) FROM home_promo"))).scalar_one() == 0
        assert await promo_service.public_view(db) is None  # no row: nothing shown

        # Column defaults make a bare insert safe and hidden.
        await db.execute(text("INSERT INTO home_promo (id, slug) VALUES (gen_random_uuid(), 'x')"))
        await db.commit()
        row = (
            await db.execute(
                text("SELECT is_active, focal_x, focal_y, tone, heading, image_src FROM home_promo")
            )
        ).one()
        assert tuple(row) == (False, 50, 50, "dark", "", "")
        await db.execute(text("DELETE FROM home_promo"))
        await db.commit()
