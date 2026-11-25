"""Tests for Alembic migration 0112_steadfast_courier_integration (Phase 23)."""

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
MIGRATION_PATH = BACKEND_ROOT / "alembic" / "versions" / "0112_steadfast_courier_integration.py"


def _load_0112_module():
    spec = importlib.util.spec_from_file_location("mig_0112", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_alembic_has_single_head_0112() -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)

    heads = script.get_heads()
    assert len(heads) == 1, f"Expected a single Alembic head, got {heads}"
    head = heads[0]
    ancestry = [rev.revision for rev in script.walk_revisions(base="base", head=head)]
    assert "0112" in ancestry, f"Expected 0112 in ancestry of {head}, got {ancestry}"

    rev = script.get_revision("0112")
    assert rev is not None
    assert rev.down_revision == "0111"

    mod = _load_0112_module()
    assert mod.revision == "0112"
    assert mod.down_revision == "0111"
    source = inspect.getsource(mod.upgrade)
    assert "drop_table" not in source
    assert "drop_column" not in source
    assert "rename_" not in source


def test_0112_upgrade_and_downgrade_schema(tmp_path: Path) -> None:
    mod = _load_0112_module()
    db_file = tmp_path / "mig0112.sqlite3"
    engine = sa.create_engine(f"sqlite:///{db_file}")

    try:
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE users (id CHAR(36) PRIMARY KEY)"))
            conn.execute(sa.text("CREATE TABLE orders (id CHAR(36) PRIMARY KEY)"))
            conn.execute(
                sa.text(
                    "CREATE TABLE order_activities ("
                    "id CHAR(36) PRIMARY KEY, "
                    "order_id CHAR(36) NOT NULL, "
                    "action VARCHAR(32) NOT NULL)"
                )
            )

            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mod.upgrade()

            inspector = sa.inspect(conn)
            tables = set(inspector.get_table_names())
            assert {
                "courier_shipments",
                "courier_webhook_events",
                "courier_locations",
            }.issubset(tables)

            ship_cols = {c["name"] for c in inspector.get_columns("courier_shipments")}
            assert {
                "id",
                "order_id",
                "provider",
                "invoice",
                "consignment_id",
                "tracking_code",
                "cod_amount",
                "delivery_status",
                "return_status",
                "is_final",
                "is_return_received",
                "tracking_events",
                "last_synced_at",
                "booked_by_id",
                "booked_at",
                "settled_payment_id",
                "settled_amount",
                "settled_at",
                "raw_payload",
                "created_at",
                "updated_at",
            }.issubset(ship_cols)

            wh_cols = {c["name"] for c in inspector.get_columns("courier_webhook_events")}
            assert {
                "id",
                "provider",
                "event_key",
                "event_type",
                "consignment_id",
                "invoice",
                "payload",
                "processed_at",
                "created_at",
            }.issubset(wh_cols)

            loc_cols = {c["name"] for c in inspector.get_columns("courier_locations")}
            assert {"id", "provider", "district", "police_station", "synced_at"}.issubset(loc_cols)

            ship_indexes = {idx["name"] for idx in inspector.get_indexes("courier_shipments")}
            assert "uq_courier_shipments_consignment_id" in ship_indexes

            loc_indexes = {idx["name"] for idx in inspector.get_indexes("courier_locations")}
            assert "uq_courier_locations_provider_district_ps" in loc_indexes

            # Partial unique index allows multiple NULL consignment_ids while rejecting duplicates
            conn.execute(
                sa.text(
                    "INSERT INTO courier_shipments "
                    "(id, provider, invoice, consignment_id, tracking_code, cod_amount, "
                    "delivery_status, is_final, is_return_received, tracking_events, raw_payload, "
                    "created_at, updated_at) "
                    "VALUES "
                    "('00000000-0000-0000-0000-000000000001', 'steadfast', 'ORD-1', NULL, '', 0, "
                    "'in_review', 0, 0, '[]', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                    "('00000000-0000-0000-0000-000000000002', 'steadfast', 'ORD-2', NULL, '', 0, "
                    "'in_review', 0, 0, '[]', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

            ctx_down = MigrationContext.configure(conn)
            with Operations.context(ctx_down):
                mod.downgrade()

            tables_after = set(sa.inspect(conn).get_table_names())
            assert "courier_shipments" not in tables_after
            assert "courier_webhook_events" not in tables_after
            assert "courier_locations" not in tables_after
    finally:
        engine.dispose()
