from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.shipping.block import BlockAdmin, BlockPublic, BlockWrite
from app.services.shipping import block_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=BlockPublic)
async def read_shipping_block(db: DbSession) -> BlockPublic:
    return await block_service.public_view(db)


@admin_router.get("", response_model=BlockAdmin)
async def read_admin_shipping_block(db: DbSession) -> BlockAdmin:
    return await block_service.admin_view(db)


@admin_router.patch("", response_model=BlockAdmin)
async def update_shipping_block(db: DbSession, payload: BlockWrite) -> BlockAdmin:
    return await block_service.update_block(db, payload)
