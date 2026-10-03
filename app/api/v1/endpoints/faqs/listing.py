from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.faqs.listing import ListingAdmin, ListingPublic, ListingWrite
from app.services.faqs import listing_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=ListingPublic)
async def read_faq_listing(db: DbSession) -> ListingPublic:
    return await listing_service.public_view(db)


@admin_router.get("", response_model=ListingAdmin)
async def read_admin_faq_listing(db: DbSession) -> ListingAdmin:
    return await listing_service.admin_view(db)


@admin_router.patch("", response_model=ListingAdmin)
async def update_faq_listing(db: DbSession, payload: ListingWrite) -> ListingAdmin:
    return await listing_service.update_listing(db, payload)
