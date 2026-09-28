import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def list_users(db: AsyncSession, offset: int, limit: int) -> tuple[list[User], int]:
    total = await db.scalar(select(func.count()).select_from(User)) or 0
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result.scalars().all()), total


async def create_user(db: AsyncSession, payload: UserCreate) -> User:
    if await get_by_email(db, payload.email):
        raise ConflictError("A user with this email already exists")

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _other_active_superadmins(db: AsyncSession, user_id: uuid.UUID) -> int:
    total = await db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.role == UserRole.SUPERADMIN,
            User.is_active.is_(True),
            User.id != user_id,
        )
    )
    return int(total or 0)


async def update_user(db: AsyncSession, user: User, payload: UserUpdate, *, actor: User) -> User:
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    email = data.pop("email", None)

    if email is not None:
        normalized = str(email).lower()
        existing = await get_by_email(db, normalized)
        if existing is not None and existing.id != user.id:
            raise ConflictError("A user with this email already exists")

    if user.id == actor.id and data.get("is_active") is False:
        raise PermissionDeniedError("You cannot disable your own account")
    if user.id == actor.id and "role" in data and data["role"] != user.role:
        raise PermissionDeniedError("You cannot change your own role")

    next_role = data.get("role", user.role)
    next_active = data.get("is_active", user.is_active)
    losing_access = (
        user.role == UserRole.SUPERADMIN
        and user.is_active
        and (next_role != UserRole.SUPERADMIN or next_active is False)
    )
    if losing_access and await _other_active_superadmins(db, user.id) == 0:
        raise PermissionDeniedError("The last active superadmin must keep that role")

    if email is not None:
        user.email = str(email).lower()
    if password:
        user.password_hash = hash_password(password)
    for field, value in data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user: User, *, actor: User) -> None:
    if user.id == actor.id:
        raise PermissionDeniedError("You cannot delete your own account")
    if (
        user.role == UserRole.SUPERADMIN
        and user.is_active
        and await _other_active_superadmins(db, user.id) == 0
    ):
        raise PermissionDeniedError("The last active superadmin cannot be deleted")
    await db.delete(user)
    await db.commit()


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await get_by_email(db, email)
    # Always run a hash comparison so a missing account and a wrong password
    # take roughly the same time and cannot be told apart.
    reference_hash = user.password_hash if user else hash_password("invalid-placeholder")
    password_ok = verify_password(password, reference_hash)

    if user is None or not password_ok:
        raise AuthenticationError("Incorrect email or password")
    if not user.is_active:
        raise AuthenticationError("This account is disabled")

    user.last_login_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    return user


async def change_password(db: AsyncSession, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise AuthenticationError("Current password is incorrect")
    user.password_hash = hash_password(new)
    await db.commit()
