"""Throwaway PostgreSQL database for the integration layer.

Unit tests keep using SQLite. This database is created beside the catalog
and dropped when the suite finishes. The catalog itself is never written.
"""

from urllib.parse import quote_plus

import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  — register every table before create_all
from app.core.config import settings
from app.db.base import Base

TEST_DATABASE = "implesia_mart_integration"


def test_url() -> str:
    user = quote_plus(settings.postgres_user)
    password = quote_plus(settings.postgres_password)
    return (
        f"postgresql+asyncpg://{user}:{password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{TEST_DATABASE}"
    )


async def _connect() -> asyncpg.Connection:
    if settings.postgres_db == TEST_DATABASE:
        raise RuntimeError("Integration tests must not use the catalog database")
    return await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
        timeout=2,
    )


async def ping() -> None:
    conn = await _connect()
    await conn.close()


async def recreate() -> None:
    conn = await _connect()
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
    finally:
        await conn.close()


async def create_schema(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def drop() -> None:
    conn = await _connect()
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')
    finally:
        await conn.close()
