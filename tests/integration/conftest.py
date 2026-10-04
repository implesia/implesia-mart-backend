"""PostgreSQL integration fixtures.

`tests/` stays the fast SQLite unit layer. Modules in this folder open real
PostgreSQL sessions for transactions, concurrency, constraints, locking,
stock, and unique keys. They skip together when the server is down.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base
from tests.integration.postgres import create_schema, drop, ping, recreate, test_url


@pytest.fixture(scope="session")
def integration_database() -> Iterator[str]:
    try:
        asyncio.run(ping())
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        pytest.skip(f"PostgreSQL is not available for integration tests: {exc}")
    asyncio.run(recreate())
    url = test_url()
    try:
        asyncio.run(create_schema(url))
        yield url
    finally:
        asyncio.run(drop())


@pytest.fixture
async def pg(
    integration_database: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(integration_database, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with factory() as db:
        await db.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
        await db.commit()
    try:
        yield factory
    finally:
        await engine.dispose()
