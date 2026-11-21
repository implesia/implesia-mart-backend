from fastapi import APIRouter, Depends, Response

from app.api.deps import DbSession, no_store, require_module_for_method
from app.schemas.site_settings import SiteSettingsRead, SiteSettingsUpdate
from app.services import site_settings_service

# Clients and a shared cache may keep this for a minute. The handler still
# reads the database, so a request that misses the cache sees the latest row.
PUBLIC_CACHE = "public, max-age=60"

public_router = APIRouter()
admin_router = APIRouter(
    dependencies=[Depends(require_module_for_method("cms")), Depends(no_store)]
)


@public_router.get("", response_model=SiteSettingsRead)
async def read_settings(response: Response, db: DbSession) -> SiteSettingsRead:
    """Home/default SEO. Null fields mean the storefront keeps its built-in copy."""
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return await site_settings_service.public_view(db)


@admin_router.get("", response_model=SiteSettingsRead)
async def read_settings_admin(db: DbSession) -> SiteSettingsRead:
    return await site_settings_service.admin_view(db)


@admin_router.patch("", response_model=SiteSettingsRead)
async def update_settings(db: DbSession, payload: SiteSettingsUpdate) -> SiteSettingsRead:
    return await site_settings_service.update(db, payload)
