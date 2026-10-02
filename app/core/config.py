from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]

# NoDecode stops pydantic-settings from JSON-parsing the raw env value, so the
# "before" validator below can accept a plain comma separated string.
CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # Application
    environment: Environment = "local"
    debug: bool = False
    # Separate from debug: echoing every statement drowns out the request logs.
    sql_echo: bool = False
    project_name: str = "Implesia Mart Backend"
    api_v1_prefix: str = "/api/v1"
    media_root: Path = Path("media")
    cors_origins: CsvList = Field(default_factory=list)

    # Security
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    jwt_algorithm: str = "HS256"

    # Database
    postgres_host: str = "localhost"
    postgres_port: int = 5434
    postgres_user: str = "implesia_mart"
    postgres_password: str = "implesia_mart"
    postgres_db: str = "implesia_mart"
    database_url_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL_OVERRIDE", "DATABASE_URL"),
    )

    # Redis
    redis_url: str = "redis://localhost:6381/0"

    # Rate limiting
    rate_limit_default: str = "200/minute"
    rate_limit_orders: str = "5/hour"
    rate_limit_product_writes: str = "30/minute"
    rate_limit_cart_writes: str = "60/minute"
    max_image_bytes: int = 5 * 1024 * 1024

    # Bootstrap superuser
    first_superuser_email: str = "admin@implesia.com"
    first_superuser_password: str = "change-me-too"

    # Email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    email_from: str = "no-reply@implesia.com"
    email_from_name: str = "Implesia Mart"
    order_notification_recipients: CsvList = Field(default_factory=list)

    # Cloudflare Turnstile
    turnstile_secret_key: str = ""

    @field_validator("cors_origins", "order_notification_recipients", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return _asyncpg_url(self.database_url_override)
        return _asyncpg_url(
            str(
                PostgresDsn.build(
                    scheme="postgresql+asyncpg",
                    username=self.postgres_user,
                    password=self.postgres_password,
                    host=self.postgres_host,
                    port=self.postgres_port,
                    path=self.postgres_db,
                )
            )
        )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def emails_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def turnstile_enabled(self) -> bool:
        return bool(self.turnstile_secret_key)


def _asyncpg_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("sqlite"):
        return url
    if not url.startswith("postgresql+asyncpg://"):
        return url

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    if "ssl" not in query:
        host = (parts.hostname or "").lower()
        if sslmode not in {"disable", "allow"} and host not in {
            "localhost",
            "127.0.0.1",
            "postgres",
        }:
            query["ssl"] = "require"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
