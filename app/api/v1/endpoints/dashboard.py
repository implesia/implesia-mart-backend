from fastapi import APIRouter

from app.api.deps import DbSession, RequireEditor
from app.schemas.dashboard import DashboardSummary
from app.services import dashboard_service

router = APIRouter()


@router.get("", response_model=DashboardSummary)
async def read_dashboard(_: RequireEditor, db: DbSession) -> DashboardSummary:
    return await dashboard_service.summary(db)
