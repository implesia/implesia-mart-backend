import os

# Must be set before any app module reads the cached Settings instance.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "SECRET_KEY": "test-secret-key-not-used-in-production",
        "DATABASE_URL_OVERRIDE": "sqlite+aiosqlite:///:memory:",
        "REDIS_URL": "memory://",
        "CORS_ORIGINS": "http://testserver",
        "SMTP_HOST": "",
        "TURNSTILE_SECRET_KEY": "",
    }
)

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402, F401  (registers users and products on Base.metadata)
from app.api.deps import get_db  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import UserRole  # noqa: E402
from app.schemas.user import UserCreate  # noqa: E402
from app.services import user_service  # noqa: E402

TEST_PASSWORD = "sup3r-secret-passphrase"


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    # StaticPool keeps the in-memory database alive across connections.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
    app.dependency_overrides.clear()


@pytest.fixture
async def superadmin_token(db_session: AsyncSession, client: AsyncClient) -> str:
    await user_service.create_user(
        db_session,
        UserCreate(
            email="admin@implesia.com",
            full_name="Implesia Mart Admin",
            password=TEST_PASSWORD,
            role=UserRole.SUPERADMIN,
        ),
    )
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


@pytest.fixture
def auth_headers(superadmin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {superadmin_token}"}
