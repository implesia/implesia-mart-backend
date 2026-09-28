from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_pool_options: dict[str, object] = {}
if not settings.database_url.startswith("sqlite"):
    pool_size = 2 if settings.is_production else 10
    _pool_options = {
        "pool_pre_ping": True,
        "pool_size": pool_size,
        "max_overflow": pool_size,
    }

engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo and not settings.is_production,
    **_pool_options,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
