import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, status

from app.api.deps import DbSession, RequireSuperadmin, require_superadmin
from app.schemas.common import PaginationParams, page_count
from app.schemas.user import (
    RoleCreate,
    RoleDeleteImpact,
    RoleDeleteRequest,
    RoleRead,
    RolesMatrixResponse,
    RolesMatrixUpdateRequest,
    RoleUpdate,
    UserCreate,
    UserListResponse,
    UserRead,
    UserUpdate,
)
from app.services import permission_service, user_service

router = APIRouter(dependencies=[Depends(require_superadmin)])


@router.get("", response_model=UserListResponse)
async def list_users(
    db: DbSession,
    pagination: Annotated[PaginationParams, Depends()],
    role: Annotated[str | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> UserListResponse:
    users, total, summary = await user_service.list_users(
        db,
        pagination.offset,
        pagination.page_size,
        role=role,
        is_active=is_active,
        q=q,
    )
    return UserListResponse(
        items=[UserRead.model_validate(user) for user in users],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        pages=page_count(total, pagination.page_size),
        summary=summary,
    )


@router.get("/roles-matrix", response_model=RolesMatrixResponse)
async def read_roles_matrix(db: DbSession) -> RolesMatrixResponse:
    return await permission_service.get_dynamic_roles_matrix(db)


@router.put("/roles-matrix", response_model=RolesMatrixResponse)
async def update_roles_matrix(
    db: DbSession,
    payload: RolesMatrixUpdateRequest,
    actor: RequireSuperadmin,
) -> RolesMatrixResponse:
    return await permission_service.update_role_permissions(db, payload.updates, actor=actor)


@router.post("/roles-matrix/reset", response_model=RolesMatrixResponse)
async def reset_roles_matrix(
    db: DbSession,
    actor: RequireSuperadmin,
) -> RolesMatrixResponse:
    return await permission_service.reset_role_permissions(db, actor=actor)


@router.get("/roles", response_model=list[RoleRead])
async def list_roles(db: DbSession) -> list[RoleRead]:
    return await permission_service.list_roles(db)


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(
    db: DbSession,
    payload: RoleCreate,
    actor: RequireSuperadmin,
) -> RoleRead:
    return await permission_service.create_role(db, payload, actor=actor)


@router.patch("/roles/{slug}", response_model=RoleRead)
async def update_role(
    db: DbSession,
    slug: str,
    payload: RoleUpdate,
    actor: RequireSuperadmin,
) -> RoleRead:
    return await permission_service.update_role(db, slug, payload, actor=actor)


@router.get("/roles/{slug}/delete-impact", response_model=RoleDeleteImpact)
async def role_delete_impact(db: DbSession, slug: str) -> RoleDeleteImpact:
    return await permission_service.get_role_delete_impact(db, slug)


@router.delete("/roles/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    db: DbSession,
    slug: str,
    actor: RequireSuperadmin,
    reassign_to_role: Annotated[str | None, Query(max_length=50)] = None,
    payload: RoleDeleteRequest | None = Body(default=None),
) -> None:
    target = reassign_to_role or (payload.reassign_to_role if payload else None)
    await permission_service.delete_role(
        db,
        slug,
        reassign_to_role=target,
        actor=actor,
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
