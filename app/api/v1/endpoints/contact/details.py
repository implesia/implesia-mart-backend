from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.contact.details import DetailsAdmin, DetailsPublic, DetailsWrite
from app.services.contact import details_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=DetailsPublic)
async def read_contact_details(db: DbSession) -> DetailsPublic:
    return await details_service.public_view(db)


@admin_router.get("", response_model=DetailsAdmin)
async def read_admin_contact_details(db: DbSession) -> DetailsAdmin:
    return await details_service.admin_view(db)


@admin_router.patch("", response_model=DetailsAdmin)
async def update_contact_details(db: DbSession, payload: DetailsWrite) -> DetailsAdmin:
    return await details_service.update_details(db, payload)
