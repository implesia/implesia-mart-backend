from fastapi import APIRouter, Depends

from app.api.deps import DbSession, no_store, require_editor
from app.schemas.about.mission import MissionCardRead, MissionCardWrite, MissionPublic
from app.services.about import mission_service

public_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_editor), Depends(no_store)])


@public_router.get("", response_model=MissionPublic)
async def read_about_mission(db: DbSession) -> MissionPublic:
    return await mission_service.public_cards(db)


@admin_router.get("", response_model=list[MissionCardRead])
async def list_about_mission(db: DbSession) -> list[MissionCardRead]:
    return await mission_service.list_cards(db)


@admin_router.patch("/{card_key}", response_model=MissionCardRead)
async def update_about_mission_card(
    db: DbSession, card_key: str, payload: MissionCardWrite
) -> MissionCardRead:
    card = await mission_service.get_card(db, card_key)
    return await mission_service.update_card(db, card, payload)
