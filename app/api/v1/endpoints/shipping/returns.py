from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.shipping.returns import ReturnsAdmin, ReturnsPublic, ReturnsWrite
from app.services.shipping import returns_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=ReturnsPublic)
async def read_shipping_returns(db: DbSession) -> ReturnsPublic:
    return await returns_service.public_view(db)


@admin_router.get("", response_model=ReturnsAdmin)
async def read_admin_shipping_returns(db: DbSession) -> ReturnsAdmin:
    return await returns_service.admin_view(db)


@admin_router.patch("", response_model=ReturnsAdmin)
async def update_shipping_returns(db: DbSession, payload: ReturnsWrite) -> ReturnsAdmin:
    return await returns_service.update_returns(db, payload)
