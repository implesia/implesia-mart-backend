"""Tests for Alembic migration 0108_communication_system (Phase 19)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "0108_communication_system.py"


def _load_0108_module():
    spec = importlib.util.spec_from_file_location("mig_0108", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_alembic_has_single_head_0108() -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)

    heads = script.get_heads()
    assert heads == ["0108"], f"Expected single Alembic head ['0108'], got {heads}"

    rev = script.get_revision("0108")
    assert rev is not None
    assert rev.down_revision == "0107"


def test_0108_upgrade_and_downgrade_schema_and_rbac_seed(tmp_path: Path) -> None:
    mod = _load_0108_module()
    db_file = tmp_path / "mig0108.sqlite3"
    engine = sa.create_engine(f"sqlite:///{db_file}")

    try:
        with engine.begin() as conn:
            # Create minimal referenced parent tables expected before 0108
            conn.execute(sa.text("CREATE TABLE users (id CHAR(36) PRIMARY KEY)"))
            conn.execute(sa.text("CREATE TABLE orders (id CHAR(36) PRIMARY KEY)"))
            conn.execute(sa.text("CREATE TABLE products (id CHAR(36) PRIMARY KEY)"))
            conn.execute(sa.text("CREATE TABLE roles (slug VARCHAR(50) PRIMARY KEY)"))
            conn.execute(
                sa.text(
                    "CREATE TABLE role_permissions ("
                    "id CHAR(36) PRIMARY KEY, "
                    "role VARCHAR(50) NOT NULL, "
                    "module_key VARCHAR(64) NOT NULL, "
                    "access_level VARCHAR(20) NOT NULL)"
                )
            )
            conn.execute(sa.text("INSERT INTO roles (slug) VALUES ('editor'), ('viewer')"))

            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mod.upgrade()

            inspector = sa.inspect(conn)
            tables = set(inspector.get_table_names())
            assert {"conversations", "messages", "conversation_read_states"}.issubset(tables)

            conv_cols = {c["name"] for c in inspector.get_columns("conversations")}
            assert {
                "id",
                "type",
                "customer_id",
                "seller_id",
                "order_id",
                "product_id",
                "assigned_staff_id",
                "subject",
                "status",
                "last_message_at",
                "last_message_preview",
                "created_at",
                "updated_at",
            }.issubset(conv_cols)

            msg_cols = {c["name"] for c in inspector.get_columns("messages")}
            assert {
                "id",
                "conversation_id",
                "sender_id",
                "sender_role",
                "body",
                "attachment_url",
                "is_internal_note",
                "created_at",
            }.issubset(msg_cols)

            rs_pk = inspector.get_pk_constraint("conversation_read_states")
            assert set(rs_pk["constrained_columns"]) == {"conversation_id", "user_id"}

            conv_indexes = {idx["name"] for idx in inspector.get_indexes("conversations")}
            assert {
                "ix_conversations_customer_last_msg",
                "ix_conversations_seller_last_msg",
                "ix_conversations_type_status_last_msg",
            }.issubset(conv_indexes)

            msg_indexes = {idx["name"] for idx in inspector.get_indexes("messages")}
            assert "ix_messages_conv_created_id" in msg_indexes

            seeded = dict(
                conn.execute(
                    sa.text(
                        "SELECT role, access_level FROM role_permissions "
                        "WHERE module_key = 'communication'"
                    )
                ).all()
            )
            assert seeded == {"editor": "read_write", "viewer": "read_only"}

            # Downgrade cleanly removes tables and seeded communication rows
            ctx_down = MigrationContext.configure(conn)
            with Operations.context(ctx_down):
                mod.downgrade()

            inspector_after = sa.inspect(conn)
            tables_after = set(inspector_after.get_table_names())
            assert "conversations" not in tables_after
            assert "messages" not in tables_after
            assert "conversation_read_states" not in tables_after

            remaining_seeded = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM role_permissions WHERE module_key = 'communication'"
                )
            ).scalar()
            assert remaining_seeded == 0
    finally:
        engine.dispose()
