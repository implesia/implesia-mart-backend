from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import DbSession, no_store
from app.core.config import settings
from app.rate_limit import limiter
from app.schemas.search import SearchQuery, SearchResults
from app.services import search_service

router = APIRouter(dependencies=[Depends(no_store)])


@router.get("", response_model=SearchResults)
@limiter.limit(settings.rate_limit_search)
async def search(
    request: Request,
    db: DbSession,
    query: Annotated[SearchQuery, Depends()],
) -> SearchResults:
    return await search_service.search(db, query)
