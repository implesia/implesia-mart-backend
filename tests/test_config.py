import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_SECRET_KEY, Settings

PRODUCTION_SECRET = "production-secret-key-with-enough-length"


def _production(secret: str) -> Settings:
    return Settings(environment="production", secret_key=secret)


def test_production_rejects_a_missing_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY is required in production"):
        _production("   ")


def test_production_rejects_the_default_secret() -> None:
    with pytest.raises(ValidationError, match="must not use the default value"):
        _production(DEFAULT_SECRET_KEY)


def test_production_rejects_a_short_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        _production("short-but-not-the-default-value")


def test_production_accepts_a_long_unique_secret() -> None:
    settings = _production(PRODUCTION_SECRET)
    assert settings.secret_key == PRODUCTION_SECRET


def test_local_can_keep_the_default_secret() -> None:
    settings = Settings(environment="local", secret_key=DEFAULT_SECRET_KEY)
    assert settings.secret_key == DEFAULT_SECRET_KEY
