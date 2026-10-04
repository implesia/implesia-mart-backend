"""Compose stays a local stack. Production boots from the Render blueprint."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_cannot_boot_as_production() -> None:
    text = (ROOT / "docker-compose.yml").read_text()
    assert "ENVIRONMENT: local" in text
    assert 'DATABASE_URL: ""' in text
    assert "--reload" in text
    assert "gunicorn" not in text


def test_backup_runbook_covers_retention_and_restore() -> None:
    text = (ROOT / "docs" / "backup-restore.md").read_text()
    readme = (ROOT / "README.md").read_text()
    assert "docs/backup-restore.md" in readme
    assert "point-in-time" in text
    assert "30 days" in text
    assert "pg_restore" in text
    assert "Monthly restore test" in text
    assert "implesia-mart-db-restore-test" in text


def test_rollback_runbook_keeps_image_and_migration_steps() -> None:
    text = (ROOT / "docs" / "rollback.md").read_text()
    readme = (ROOT / "README.md").read_text()
    start = (ROOT / "scripts" / "start.sh").read_text()
    assert "docs/rollback.md" in readme
    assert "docs/rollback.md" in start
    assert "alembic upgrade head" in start
    assert "downgrade" not in start
    assert "Rollback" in text
    assert "alembic downgrade -1" in text
    assert "alembic current" in text


def test_production_api_stays_one_instance_while_media_is_local() -> None:
    blueprint = (ROOT / "render.yaml").read_text()
    readme = (ROOT / "README.md").read_text()
    assert "numInstances: 1" in blueprint
    assert "object storage" in readme


def test_public_cms_cache_stays_off_private_routes() -> None:
    readme = (ROOT / "README.md").read_text()
    deps = (ROOT / "app/api/deps.py").read_text()
    cart = (ROOT / "app/api/v1/endpoints/cart.py").read_text()
    orders = (ROOT / "app/api/v1/endpoints/orders.py").read_text()
    assert "30 seconds" in readme
    assert "no-store" in readme
    assert "no-store" in deps
    assert "no_store" in cart
    assert "no_store" in orders


def test_guest_cart_cleanup_is_deferred() -> None:
    readme = (ROOT / "README.md").read_text()
    model = (ROOT / "app/models/cart.py").read_text()
    assert "unused guest cart" in readme
    assert "guest_token_hash" in model
    assert "updated_at" in model


def test_cms_packages_stay_separate() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "shared helper" in readme
    assert "CMS framework" in readme
    for name in (
        "home",
        "about",
        "sustainability",
        "shipping",
        "privacy",
        "faqs",
        "contact",
        "blogs",
    ):
        assert (ROOT / "app/services" / name).is_dir()


def test_readme_matches_built_features() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "will be added" not in readme
    assert "not built" not in readme.lower()
    for phrase in (
        "## Current features",
        "## API structure",
        "## Environment setup",
        "## Admin roles",
        "## Migration",
        "## Testing",
        "## Deployment",
        "## Production setup",
        "/api/v1/orders",
        "superadmin",
    ):
        assert phrase in readme


def test_render_boots_gunicorn_without_reload() -> None:
    blueprint = (ROOT / "render.yaml").read_text()
    start = (ROOT / "scripts" / "start.sh").read_text()
    assert "value: production" in blueprint
    assert "dockerCommand: sh scripts/start.sh" in blueprint
    assert "fromDatabase:" in blueprint
    assert "fromService:" in blueprint
    assert blueprint.count("generateValue: true") >= 2
    assert "--reload" not in blueprint
    assert "gunicorn" in start
    assert "--reload" not in start
