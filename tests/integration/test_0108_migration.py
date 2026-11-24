"""Migration 0108 inserts missing roles and does not rewrite existing rows."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import hash_password
from app.models.user import User
from app.services.permission_service import LEGACY_ROLE_SLUGS

pytestmark = pytest.mark.postgres

MIGRATION = Path(__file__).parents[2] / "alembic" / "versions" / "0108_seed_missing_roles.py"


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("migration_0108", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run(db: AsyncSession) -> None:
    module = _migration()

    def go(sync_conn) -> None:  # type: ignore[no-untyped-def]
        with Operations.context(MigrationContext.configure(sync_conn)):
            module.upgrade()

    conn = await db.connection()
    await conn.run_sync(go)
    await db.commit()


async def _slugs(db: AsyncSession) -> set[str]:
    rows = await db.execute(text("SELECT slug FROM roles"))
    return {row[0] for row in rows}


async def _restore_user_fk(db: AsyncSession) -> None:
    await db.execute(
        text(
            """
            UPDATE users
            SET role = 'viewer'
            WHERE role NOT IN (SELECT slug FROM roles)
            """
        )
    )
    await db.execute(
        text(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_role_roles'
              ) THEN
                ALTER TABLE users
                  ADD CONSTRAINT fk_users_role_roles
                  FOREIGN KEY (role) REFERENCES roles (slug)
                  ON UPDATE CASCADE ON DELETE RESTRICT;
              END IF;
            END $$;
            """
        )
    )
    await db.commit()


async def test_0108_seeds_missing_roles_without_rewriting_users(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    module = _migration()
    assert module.revision == "0108"
    assert module.down_revision == "0107"
    assert {row[0] for row in LEGACY_ROLE_SLUGS} == {row["slug"] for row in module._LEGACY_ROLES}

    user_id = uuid.uuid4()
    email = f"legacy-{user_id.hex[:8]}@implesia.test"
    password_hash = hash_password("legacy-passphrase")

    async with pg() as db:
        before_viewer = (
            await db.execute(
                text("SELECT id, label, admin_access, is_system FROM roles WHERE slug = 'viewer'")
            )
        ).one()
        db.add(
            User(
                id=user_id,
                email=email,
                full_name="Legacy Clerk",
                password_hash=password_hash,
                role="viewer",
                is_active=True,
            )
        )
        await db.commit()
        await db.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_users_role_roles"))
        await db.execute(
            text("UPDATE users SET role = 'night_clerk' WHERE id = :id"),
            {"id": user_id},
        )
        await db.commit()
        snapshot = (
            await db.execute(
                text(
                    "SELECT id, email, full_name, password_hash, role, is_active "
                    "FROM users WHERE id = :id"
                ),
                {"id": user_id},
            )
        ).one()

    try:
        async with pg() as db:
            await _run(db)
            slugs = await _slugs(db)
            assert {
                "superadmin",
                "editor",
                "viewer",
                "customer",
                "super_admin",
                "admin",
                "staff",
                "night_clerk",
            } <= slugs
            legacy = (
                await db.execute(
                    text(
                        "SELECT admin_access, is_system FROM roles WHERE slug = 'super_admin'"
                    )
                )
            ).one()
            assert legacy == (False, False)
            kept = (
                await db.execute(
                    text(
                        "SELECT id, email, full_name, password_hash, role, is_active "
                        "FROM users WHERE id = :id"
                    ),
                    {"id": user_id},
                )
            ).one()
            assert tuple(kept) == tuple(snapshot)

            viewer_after = (
                await db.execute(
                    text(
                        "SELECT id, label, admin_access, is_system "
                        "FROM roles WHERE slug = 'viewer'"
                    )
                )
            ).one()
            assert tuple(viewer_after) == tuple(before_viewer)

            await _run(db)
            viewer_again = (
                await db.execute(text("SELECT id FROM roles WHERE slug = 'viewer'"))
            ).scalar_one()
            assert viewer_again == before_viewer[0]
    finally:
        async with pg() as db:
            await _restore_user_fk(db)
