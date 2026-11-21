import uuid
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableError,
)
from app.core.logging import get_logger
from app.core.security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.models.audit_event import AuditAction
from app.models.user import User, UserRole
from app.schemas.user import (
    UserCreate,
    UserSummaryCounts,
    UserUpdate,
)
from app.services import audit_service, login_alert, permission_service, refresh_token_service

logger = get_logger("auth")

# One message for a missing account, a wrong password, and a disabled account.
_INVALID_LOGIN = "Invalid email or password."

_ROLE_ORDER: dict[str, int] = {
    UserRole.CUSTOMER.value: -1,
    UserRole.VIEWER.value: 0,
    UserRole.EDITOR.value: 1,
    UserRole.SUPERADMIN.value: 2,
}


async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def list_users(
    db: AsyncSession,
    offset: int,
    limit: int,
    *,
    role: str | None = None,
    is_active: bool | None = None,
    q: str | None = None,
) -> tuple[list[User], int, UserSummaryCounts]:
    await permission_service.ensure_system_roles(db)
    staff_values = tuple(await permission_service.get_admin_role_slugs(db))
    summary_row = (
        await db.execute(
            select(
                func.count(User.id).label("total_users"),
                func.coalesce(func.sum(case((User.role.in_(staff_values), 1), else_=0)), 0).label(
                    "staff_count"
                ),
                func.coalesce(
                    func.sum(case((User.role == UserRole.CUSTOMER.value, 1), else_=0)), 0
                ).label("customer_count"),
                func.coalesce(func.sum(case((User.is_active.is_(True), 1), else_=0)), 0).label(
                    "active_count"
                ),
            )
        )
    ).one()
    summary = UserSummaryCounts(
        total_users=int(summary_row.total_users or 0),
        staff_count=int(summary_row.staff_count or 0),
        customer_count=int(summary_row.customer_count or 0),
        active_count=int(summary_row.active_count or 0),
    )

    conditions: list[ColumnElement[bool]] = []
    if role and role != "all":
        normalized_role = role.strip().lower()
        if normalized_role == "staff":
            conditions.append(User.role.in_(staff_values))
        else:
            existing_role = await permission_service.role_exists(db, normalized_role)
            if existing_role is None:
                return [], 0, summary
            conditions.append(User.role == existing_role.slug)

    if is_active is not None:
        conditions.append(User.is_active.is_(is_active))

    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                User.phone.ilike(pattern),
            )
        )

    count_stmt = select(func.count()).select_from(User)
    list_stmt = select(User)
    if conditions:
        count_stmt = count_stmt.where(*conditions)
        list_stmt = list_stmt.where(*conditions)

    total = int((await db.scalar(count_stmt)) or 0)
    result = await db.execute(
        list_stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
    )
    return list(result.scalars().all()), total, summary


async def create_user(db: AsyncSession, payload: UserCreate) -> User:
    if await get_by_email(db, payload.email):
        raise ConflictError("A user with this email already exists")

    await permission_service.ensure_system_roles(db)
    role_slug = str(payload.role).strip().lower()
    if await permission_service.role_exists(db, role_slug) is None:
        raise UnprocessableError(f"Unknown role: {role_slug}")

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=role_slug,
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

    if "role" in data and data["role"] is not None:
        await permission_service.ensure_system_roles(db)
        norm_role = str(data["role"]).strip().lower()
        if await permission_service.role_exists(db, norm_role) is None:
            raise UnprocessableError(f"Unknown role: {norm_role}")
        data["role"] = norm_role

    if user.id == actor.id and data.get("is_active") is False:
        raise PermissionDeniedError("You cannot disable your own account")
    if user.id == actor.id and "role" in data and data["role"] != user.role:
        raise PermissionDeniedError("You cannot change your own role")

    next_role = str(data.get("role", user.role))
    next_active = data.get("is_active", user.is_active)
    losing_access = (
        user.role == UserRole.SUPERADMIN
        and user.is_active
        and (next_role != UserRole.SUPERADMIN or next_active is False)
    )
    if losing_access and await _other_active_superadmins(db, user.id) == 0:
        raise PermissionDeniedError("The last active superadmin must keep that role")

    previous_role = str(user.role)
    previous_active = user.is_active
    if email is not None:
        user.email = str(email).lower()
    if password:
        user.password_hash = hash_password(password)
    for field, value in data.items():
        setattr(user, field, value)

    if password:
        await audit_service.record(
            db,
            actor_id=actor.id,
            action=AuditAction.PASSWORD_CHANGED,
            target_type="user",
            target_id=user.id,
            metadata={"via": "admin", "email": user.email},
        )
    if "role" in data and user.role != previous_role:
        await audit_service.record(
            db,
            actor_id=actor.id,
            action=AuditAction.ROLE_CHANGED,
            target_type="user",
            target_id=user.id,
            metadata={
                "email": user.email,
                "from": previous_role,
                "to": str(user.role),
            },
        )
    if previous_active and not user.is_active:
        await audit_service.record(
            db,
            actor_id=actor.id,
            action=AuditAction.USER_DISABLED,
            target_type="user",
            target_id=user.id,
            metadata={"email": user.email},
        )

    role_changed = str(user.role) != previous_role
    role_downgraded = _ROLE_ORDER.get(str(user.role), 0) < _ROLE_ORDER.get(previous_role, 0)
    deactivated = previous_active and not user.is_active
    if (
        role_downgraded
        or (role_changed and str(user.role) == UserRole.CUSTOMER)
        or deactivated
        or password
    ):
        await refresh_token_service.revoke_user_sessions(db, user.id)

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
    # A missing account still runs bcrypt verify, against a fixed hash.
    reference_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    password_ok = verify_password(password, reference_hash)

    if user is None or not password_ok or not user.is_active:
        if user is None:
            reason = "unknown_email"
        elif not password_ok:
            reason = "wrong_password"
        else:
            reason = "account_disabled"
        logger.info("login_failed", reason=reason, email=email.lower())
        await login_alert.note_failure(email, None if user is None else user.role)
        raise AuthenticationError(_INVALID_LOGIN)

    user.last_login_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    return user


async def change_password(db: AsyncSession, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise AuthenticationError("Current password is incorrect")
    user.password_hash = hash_password(new)
    await refresh_token_service.revoke_user_sessions(db, user.id)
    await audit_service.record(
        db,
        actor_id=user.id,
        action=AuditAction.PASSWORD_CHANGED,
        target_type="user",
        target_id=user.id,
        metadata={"via": "self", "email": user.email},
    )
    await db.commit()
