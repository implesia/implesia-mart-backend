from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]

# HS256 needs a 256-bit key. The placeholder is rejected on its own so a longer
# copy of it still cannot sign production tokens.
DEFAULT_SECRET_KEY = "change-me-in-production"
MIN_PRODUCTION_SECRET_KEY_LENGTH = 32

# Products have no reorder column. Same cutoff as report_service.LOW_STOCK_AT
# and the storefront low-stock mark. Not an environment variable.
LOW_STOCK_THRESHOLD = 5

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
    # Cloudflare R2 (S3-compatible). All five empty: files stay on media_root.
    # A partial set is refused so a deploy cannot quietly write to the
    # container disk and lose the files on the next restart.
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_access_key_id: SecretStr = SecretStr("")
    s3_secret_access_key: SecretStr = SecretStr("")
    media_public_base_url: str = ""
    cors_origins: CsvList = Field(default_factory=list)

    # Security
    secret_key: str = DEFAULT_SECRET_KEY
    # IPs or CIDRs of reverse proxies allowed to set the client address.
    # A direct caller is never trusted, even if it sends forwarding headers.
    trusted_proxies: CsvList = Field(default_factory=list)
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 14
    # Bearer token a scraper must send to read /metrics. Empty: /metrics is disabled
    # (404) in every environment. SecretStr keeps it out of reprs and logs.
    metrics_token: SecretStr = SecretStr("")

    # Database
    postgres_host: str = "localhost"
    postgres_port: int = 5434
    postgres_user: str = "implesia_mart"
    postgres_password: str = "implesia_mart"
    postgres_db: str = "implesia_mart"
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout: int = Field(default=15, ge=1, le=120)
    db_pool_recycle: int = Field(default=1800, ge=60, le=86400)
    database_url_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL_OVERRIDE", "DATABASE_URL"),
    )

    # Redis
    redis_url: str = "redis://localhost:6381/0"

    # Rate limiting
    rate_limit_default: str = "200/minute"
    rate_limit_login_ip: str = "10/minute"
    rate_limit_login_account: str = "10/minute"
    rate_limit_refresh_ip: str = "10/minute"
    rate_limit_refresh_account: str = "10/minute"
    rate_limit_orders: str = "5/hour"
    rate_limit_order_lookup: str = "30/minute"
    rate_limit_search: str = "120/minute"
    rate_limit_product_writes: str = "30/minute"
    rate_limit_cart_writes: str = "60/minute"
    rate_limit_inquiries: str = "10/hour"
    max_image_bytes: int = 5 * 1024 * 1024
    max_video_bytes: int = 50 * 1024 * 1024

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

    # Meta Conversions API. Both the pixel id and the token must be set or Purchase
    # events are not sent. The test code is optional and only used while testing.
    meta_pixel_id: str = ""
    meta_capi_token: SecretStr = SecretStr("")
    meta_test_event_code: str = ""

    # Telegram. An empty token or an empty chat list leaves alerts off.
    # Chat ids are comma-separated. Group ids are negative.
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_ids: CsvList = Field(default_factory=list)
    telegram_notify_order_cancelled: bool = False
    telegram_notify_low_stock: bool = False
    # Storefront origin, no path. The order link is {ADMIN_BASE_URL}/admin/orders/{id}.
    # The customer status link is {ADMIN_BASE_URL}/order-status?number={order number}.
    admin_base_url: str = ""

    # Customer SMS when an order is confirmed or shipped. Off until the master
    # flag is true. provider is only "log" (write the text to the log) or
    # "noop" (do nothing). There is no live SMS or WhatsApp gateway in this
    # process. See .env.example for the account a real send would need.
    customer_sms_enabled: bool = False
    customer_sms_provider: Literal["log", "noop"] = "log"
    customer_sms_on_confirmed: bool = True
    customer_sms_on_shipped: bool = True
    # Added to the order date when a packing slip asks for an estimated
    # delivery date. inside covers the city and Dhaka-suburban zones.
    # The date is computed on read. It is not stored on the order.
    delivery_days_inside_dhaka: int = Field(default=2, ge=0, le=60)
    delivery_days_outside_dhaka: int = Field(default=5, ge=0, le=60)

    @model_validator(mode="after")
    def _production_secret_key(self) -> Self:
        if self.environment != "production":
            return self
        secret = self.secret_key.strip()
        if not secret:
            raise ValueError("SECRET_KEY is required in production")
        if secret == DEFAULT_SECRET_KEY:
            raise ValueError("SECRET_KEY must not use the default value in production")
        if len(secret) < MIN_PRODUCTION_SECRET_KEY_LENGTH:
            raise ValueError(
                "SECRET_KEY must be at least "
                f"{MIN_PRODUCTION_SECRET_KEY_LENGTH} characters in production"
            )
        return self

    @model_validator(mode="after")
    def _object_storage_config(self) -> Self:
        endpoint = self.s3_endpoint_url.strip()
        bucket = self.s3_bucket.strip()
        access = self.s3_access_key_id.get_secret_value().strip()
        secret = self.s3_secret_access_key.get_secret_value().strip()
        public = self.media_public_base_url.strip()
        filled = (endpoint, bucket, access, secret, public)
        if not any(filled):
            return self
        if not all(filled):
            raise ValueError(
                "Object storage needs S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY_ID, "
                "S3_SECRET_ACCESS_KEY, and MEDIA_PUBLIC_BASE_URL set together"
            )
        if "/" in bucket or "\\" in bucket or ".." in bucket:
            raise ValueError("S3_BUCKET must be a single bucket name")
        _require_origin(endpoint, "S3_ENDPOINT_URL", production=self.environment == "production")
        _require_origin(
            public, "MEDIA_PUBLIC_BASE_URL", production=self.environment == "production"
        )
        return self

    @model_validator(mode="after")
    def _admin_base_url_origin(self) -> Self:
        raw = self.admin_base_url.strip().rstrip("/")
        if not raw:
            self.admin_base_url = ""
            return self
        _require_origin(raw, "ADMIN_BASE_URL", production=self.environment == "production")
        self.admin_base_url = raw
        return self

    @field_validator("customer_sms_provider", mode="before")
    @classmethod
    def _sms_provider(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip().lower()
            return cleaned or "log"
        return value

    @field_validator(
        "cors_origins",
        "order_notification_recipients",
        "trusted_proxies",
        "telegram_chat_ids",
        mode="before",
    )
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

    @property
    def meta_capi_enabled(self) -> bool:
        """True only when both the pixel id and the access token are set."""
        return bool(self.meta_pixel_id.strip() and self.meta_capi_token.get_secret_value().strip())

    @property
    def telegram_enabled(self) -> bool:
        """True only when a bot token and at least one chat id are set."""
        return bool(self.telegram_bot_token.get_secret_value().strip() and self.telegram_chat_ids)

    @property
    def object_storage_enabled(self) -> bool:
        """True only when every R2 setting is present. Otherwise files stay on disk."""
        return bool(
            self.s3_endpoint_url.strip()
            and self.s3_bucket.strip()
            and self.s3_access_key_id.get_secret_value().strip()
            and self.s3_secret_access_key.get_secret_value().strip()
            and self.media_public_base_url.strip()
        )


def _require_origin(url: str, name: str, *, production: bool) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ValueError(f"{name} must be an http(s) origin")
    if parts.username or parts.password:
        raise ValueError(f"{name} must not include credentials")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError(f"{name} must not include a path, query, or fragment")
    if production and parts.scheme != "https":
        raise ValueError(f"{name} must use https in production")


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
        # A single-label host is private DNS (compose "postgres", Slasher "db").
        # Those servers do not speak TLS. Public hosts still require it.
        private = "." not in host or host in {"localhost", "127.0.0.1"}
        if sslmode not in {"disable", "allow"} and not private:
            query["ssl"] = "require"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
