from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.privacy.collection import CollectionAdmin, CollectionPublic, CollectionWrite
from app.services.privacy import collection_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=CollectionPublic)
async def read_privacy_collection(db: DbSession) -> CollectionPublic:
    return await collection_service.public_view(db)


@admin_router.get("", response_model=CollectionAdmin)
async def read_admin_privacy_collection(db: DbSession) -> CollectionAdmin:
    return await collection_service.admin_view(db)


@admin_router.patch("", response_model=CollectionAdmin)
async def update_privacy_collection(db: DbSession, payload: CollectionWrite) -> CollectionAdmin:
    return await collection_service.update_collection(db, payload)
