from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.privacy.introduction import (
    IntroductionAdmin,
    IntroductionPublic,
    IntroductionWrite,
)
from app.services.privacy import introduction_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=IntroductionPublic)
async def read_privacy_introduction(db: DbSession) -> IntroductionPublic:
    return await introduction_service.public_view(db)


@admin_router.get("", response_model=IntroductionAdmin)
async def read_admin_privacy_introduction(db: DbSession) -> IntroductionAdmin:
    return await introduction_service.admin_view(db)


@admin_router.patch("", response_model=IntroductionAdmin)
async def update_privacy_introduction(
    db: DbSession, payload: IntroductionWrite
) -> IntroductionAdmin:
    return await introduction_service.update_introduction(db, payload)
