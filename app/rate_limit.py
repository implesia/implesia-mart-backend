from fastapi import Request
from slowapi import Limiter

from app.api.deps import client_ip
from app.core.config import settings


def _rate_limit_key(request: Request) -> str:
    return client_ip(request) or "anonymous"


# Redis storage keeps limits consistent across Gunicorn workers; without it each
# worker would enforce its own separate counter.
limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.redis_url,
    enabled=settings.environment != "test",
)
