from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.blogs.categories import CategoriesAdmin, CategoriesPublic, CategoriesWrite
from app.services.blogs import categories_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=CategoriesPublic)
async def read_blog_categories(db: DbSession) -> CategoriesPublic:
    return await categories_service.public_view(db)


@admin_router.get("", response_model=CategoriesAdmin)
async def read_admin_blog_categories(db: DbSession) -> CategoriesAdmin:
    return await categories_service.admin_view(db)


@admin_router.patch("", response_model=CategoriesAdmin)
async def update_blog_categories(db: DbSession, payload: CategoriesWrite) -> CategoriesAdmin:
    return await categories_service.update_categories(db, payload)
