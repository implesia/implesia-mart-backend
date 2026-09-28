from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe — checks database connectivity")
async def ready(db: DbSession) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("readiness_failed", error=str(exc))
        return {"status": "degraded", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
