from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.blogs.cta import CtaAdmin, CtaPublic, CtaWrite
from app.services.blogs import cta_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=CtaPublic)
async def read_blog_cta(db: DbSession) -> CtaPublic:
    return await cta_service.public_view(db)


@admin_router.get("", response_model=CtaAdmin)
async def read_admin_blog_cta(db: DbSession) -> CtaAdmin:
    return await cta_service.admin_view(db)


@admin_router.patch("", response_model=CtaAdmin)
async def update_blog_cta(db: DbSession, payload: CtaWrite) -> CtaAdmin:
    return await cta_service.update_cta(db, payload)
