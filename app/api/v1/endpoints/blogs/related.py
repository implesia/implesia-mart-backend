from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.blogs.related import RelatedAdmin, RelatedPublic, RelatedWrite
from app.services.blogs import related_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=RelatedPublic)
async def read_blog_related(db: DbSession) -> RelatedPublic:
    return await related_service.public_view(db)


@admin_router.get("", response_model=RelatedAdmin)
async def read_admin_blog_related(db: DbSession) -> RelatedAdmin:
    return await related_service.admin_view(db)


@admin_router.patch("", response_model=RelatedAdmin)
async def update_blog_related(db: DbSession, payload: RelatedWrite) -> RelatedAdmin:
    return await related_service.update_related(db, payload)
