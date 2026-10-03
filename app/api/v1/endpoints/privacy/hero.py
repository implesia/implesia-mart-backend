from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.privacy.hero import HeroAdmin, HeroPublic, HeroWrite
from app.services.privacy import hero_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=HeroPublic)
async def read_privacy_hero(db: DbSession) -> HeroPublic:
    return await hero_service.public_view(db)


@admin_router.get("", response_model=HeroAdmin)
async def read_admin_privacy_hero(db: DbSession) -> HeroAdmin:
    return await hero_service.admin_view(db)


@admin_router.patch("", response_model=HeroAdmin)
async def update_privacy_hero(db: DbSession, payload: HeroWrite) -> HeroAdmin:
    return await hero_service.update_hero(db, payload)
