import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.common import Message
from app.schemas.home.newsletter import (
    NewsletterAdmin,
    NewsletterCopyUpdate,
    NewsletterPerkRead,
    NewsletterPerkUpdate,
    NewsletterPerkWrite,
    NewsletterPublic,
    NewsletterReorder,
)
from app.services.home import newsletter_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=NewsletterPublic)
async def read_home_newsletter(db: DbSession) -> NewsletterPublic:
    return await newsletter_service.public_view(db)


@admin_router.get("", response_model=NewsletterAdmin)
async def list_newsletter(db: DbSession) -> NewsletterAdmin:
    return await newsletter_service.admin_view(db)


@admin_router.patch("", response_model=NewsletterAdmin)
async def update_newsletter_copy(db: DbSession, payload: NewsletterCopyUpdate) -> NewsletterAdmin:
    return await newsletter_service.update_copy(db, payload)


@admin_router.post(
    "/perks", response_model=NewsletterPerkRead, status_code=status.HTTP_201_CREATED
)
async def create_newsletter_perk(db: DbSession, payload: NewsletterPerkWrite) -> NewsletterPerkRead:
    return await newsletter_service.create_perk(db, payload)


@admin_router.put("/perks/order", response_model=NewsletterAdmin)
async def reorder_newsletter_perks(db: DbSession, payload: NewsletterReorder) -> NewsletterAdmin:
    return await newsletter_service.reorder(db, payload)


@admin_router.patch("/perks/{perk_id}", response_model=NewsletterPerkRead)
async def update_newsletter_perk(
    db: DbSession, perk_id: uuid.UUID, payload: NewsletterPerkUpdate
) -> NewsletterPerkRead:
    perk = await newsletter_service.get_perk(db, perk_id)
    return await newsletter_service.update_perk(db, perk, payload)


@admin_router.delete("/perks/{perk_id}", response_model=Message)
async def delete_newsletter_perk(db: DbSession, perk_id: uuid.UUID) -> Message:
    perk = await newsletter_service.get_perk(db, perk_id)
    await newsletter_service.delete_perk(db, perk)
    return Message(message="Perk removed")
