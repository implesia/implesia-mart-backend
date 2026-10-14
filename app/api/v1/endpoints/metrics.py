import asyncio
import hmac

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import text

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.metrics import CONTENT_TYPE_LATEST, render_http_metrics
from app.rate_limit import limiter, rate_limit_store_ready

logger = get_logger(__name__)

router = APIRouter()


async def database_up() -> bool:
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("metrics_probe_failed", dependency="database", error=str(exc))
        return False


def _gauge(name: str, documentation: str, up: bool) -> bytes:
    value = 1 if up else 0
    return (f"# HELP {name} {documentation}\n# TYPE {name} gauge\n{name} {value}\n").encode()


def _allowed(request: Request) -> bool:
    """Checked on every scrape. No token configured means the endpoint is off (404) in
    every environment: there is no unauthenticated mode to forget about."""
    token = settings.metrics_token.get_secret_value()
    if not token:
        return False
    given = request.headers.get("authorization", "")
    return hmac.compare_digest(given.encode(), f"Bearer {token}".encode())


@router.get("/metrics", summary="Request and dependency metrics")
@limiter.exempt
async def metrics(request: Request) -> Response:
    """Counters and a latency histogram, plus a live Postgres and Redis probe.

    Rates are the increase in the counters between scrapes. Probes are not
    counted as requests.
    """
    if not _allowed(request):
        # 404 rather than 401 so the endpoint is not advertised on the public hostname.
        raise NotFoundError("Not found")
    database = await database_up()
    redis_ok = await asyncio.to_thread(rate_limit_store_ready)
    body = render_http_metrics()
    body += _gauge("database_up", "1 when Postgres accepts SELECT 1.", database)
    body += _gauge("redis_up", "1 when the rate-limit store answers.", redis_ok)
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)
