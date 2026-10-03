from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, RequireEditor, no_store
from app.schemas.dashboard import DashboardOverview, DashboardRange
from app.services import dashboard_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("", response_model=DashboardOverview)
async def read_dashboard(
    _: RequireEditor,
    db: DbSession,
    span: Annotated[DashboardRange, Query(alias="range")] = "7d",
    start: Annotated[date | None, Query(alias="from")] = None,
    end: Annotated[date | None, Query(alias="to")] = None,
) -> DashboardOverview:
    return await dashboard_service.overview(db, span, start, end)
