from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.shipping.contents import ContentsAdmin, ContentsPublic, ContentsWrite
from app.services.shipping import contents_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=ContentsPublic)
async def read_shipping_contents(db: DbSession) -> ContentsPublic:
    return await contents_service.public_view(db)


@admin_router.get("", response_model=ContentsAdmin)
async def read_admin_shipping_contents(db: DbSession) -> ContentsAdmin:
    return await contents_service.admin_view(db)


@admin_router.patch("", response_model=ContentsAdmin)
async def update_shipping_contents(db: DbSession, payload: ContentsWrite) -> ContentsAdmin:
    return await contents_service.update_contents(db, payload)
