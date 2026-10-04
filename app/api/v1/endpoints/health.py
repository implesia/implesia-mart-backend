import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.logging import get_logger
from app.rate_limit import limiter, rate_limit_store_ready

logger = get_logger(__name__)

router = APIRouter()


@router.get("/live", summary="Liveness probe")
@limiter.exempt
async def live() -> dict[str, str]:
    """The process is up. This does not check Postgres or Redis."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe — checks database and Redis")
@limiter.exempt
async def ready(db: DbSession) -> JSONResponse:
    """Traffic-ready only when Postgres and the rate-limit store both answer.

    Postgres holds the catalog and accounts. Redis is not the system of record,
    but every worker shares rate limits through it, and there is no memory
    fallback. Either one being down means this instance should leave rotation.
    """
    database = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("readiness_failed", dependency="database", error=str(exc))
        database = "unreachable"

    redis_ok = await asyncio.to_thread(rate_limit_store_ready)
    redis_status = "ok" if redis_ok else "unreachable"
    if not redis_ok:
        logger.error("readiness_failed", dependency="redis")

    body = {"status": "ok", "database": database, "redis": redis_status}
    if database == "ok" and redis_ok:
        return JSONResponse(content=body)
    body["status"] = "unavailable"
    return JSONResponse(status_code=503, content=body)
