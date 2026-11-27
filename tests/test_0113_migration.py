"""Tests for Alembic migration 0113_home_banner_template."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "0113_home_banner_template.py"


def _load_0113_module():
    spec = importlib.util.spec_from_file_location("mig_0113", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_alembic_has_single_head_0113() -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)

    heads = script.get_heads()
    assert len(heads) == 1, f"Expected a single linear Alembic head, got {heads}"
    ancestors = {r.revision for r in script.walk_revisions(head=heads[0], base="base")}
    assert "0113" in ancestors, f"Expected 0113 in Alembic history under head {heads[0]}"

    rev = script.get_revision("0113")
    assert rev is not None
    assert rev.down_revision == "0112"

    mod = _load_0113_module()
    assert mod.revision == "0113"
    assert mod.down_revision == "0112"
    source = inspect.getsource(mod.upgrade)
    assert "drop_table" not in source
    assert "drop_column" not in source
    assert "rename_" not in source


def test_0113_upgrade_and_downgrade_schema(tmp_path: Path) -> None:
    mod = _load_0113_module()
    db_file = tmp_path / "mig0113.sqlite3"
    engine = sa.create_engine(f"sqlite:///{db_file}")

    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "CREATE TABLE home_banners ("
                    "id CHAR(36) PRIMARY KEY, "
                    "slug VARCHAR(40) NOT NULL)"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO home_banners (id, slug) "
                    "VALUES ('00000000-0000-0000-0000-000000000001', 'home')"
                )
            )

            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mod.upgrade()

            cols = {c["name"] for c in sa.inspect(conn).get_columns("home_banners")}
            assert "template" in cols

            existing_template = conn.execute(
                sa.text("SELECT template FROM home_banners WHERE slug = 'home'")
            ).scalar_one()
            assert existing_template == "classic"

            ctx_down = MigrationContext.configure(conn)
            with Operations.context(ctx_down):
                mod.downgrade()

            cols_after = {c["name"] for c in sa.inspect(conn).get_columns("home_banners")}
            assert "template" not in cols_after
    finally:
        engine.dispose()
