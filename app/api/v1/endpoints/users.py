import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, RequireSuperadmin, require_superadmin
from app.schemas.common import Page, PaginationParams
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services import user_service

router = APIRouter(dependencies=[Depends(require_superadmin)])


@router.get("", response_model=Page[UserRead])
async def list_users(
    db: DbSession,
    pagination: Annotated[PaginationParams, Depends()],
) -> Page[UserRead]:
    users, total = await user_service.list_users(db, pagination.offset, pagination.page_size)
    return Page[UserRead](
        items=[UserRead.model_validate(user) for user in users],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(db: DbSession, payload: UserCreate) -> UserRead:
    user = await user_service.create_user(db, payload)
    return UserRead.model_validate(user)


@router.get("/{user_id}", response_model=UserRead)
async def read_user(db: DbSession, user_id: uuid.UUID) -> UserRead:
    user = await user_service.get_by_id(db, user_id)
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    db: DbSession,
    user_id: uuid.UUID,
    payload: UserUpdate,
    actor: RequireSuperadmin,
) -> UserRead:
    user = await user_service.get_by_id(db, user_id)
    updated = await user_service.update_user(db, user, payload, actor=actor)
    return UserRead.model_validate(updated)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(db: DbSession, user_id: uuid.UUID, actor: RequireSuperadmin) -> None:
    user = await user_service.get_by_id(db, user_id)
    await user_service.delete_user(db, user, actor=actor)
