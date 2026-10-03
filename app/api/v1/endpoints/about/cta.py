from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.about.cta import CtaPublic, CtaRead, CtaWrite
from app.services.about import cta_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=CtaPublic)
async def read_about_cta(db: DbSession) -> CtaPublic:
    return await cta_service.public_view(db)


@admin_router.get("", response_model=CtaRead)
async def read_admin_about_cta(db: DbSession) -> CtaRead:
    return await cta_service.admin_view(db)


@admin_router.patch("", response_model=CtaRead)
async def update_about_cta(db: DbSession, payload: CtaWrite) -> CtaRead:
    return await cta_service.update_cta(db, payload)
