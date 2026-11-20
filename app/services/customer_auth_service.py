from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ConflictError
from app.core.logging import get_logger
from app.core.security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.models.audit_event import AuditAction
from app.models.order import Order
from app.models.user import User, UserRole
from app.schemas.customer import (
    CustomerProfileUpdate,
    CustomerRegisterRequest,
    normalize_bd_phone,
)
from app.services import audit_service, refresh_token_service

logger = get_logger("customer_auth")


async def get_by_phone(db: AsyncSession, phone: str) -> User | None:
    result = await db.execute(select(User).where(User.phone == phone))
    return result.scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def get_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    cleaned = identifier.strip()
    if "@" in cleaned:
        return await get_by_email(db, cleaned)

    try:
        norm_phone = normalize_bd_phone(cleaned)
        user = await get_by_phone(db, norm_phone)
        if user is not None:
            return user
    except ValueError:
        pass

    # Fallback to direct phone or email lookup if not matching BD phone regex
    user = await get_by_phone(db, cleaned)
    if user is not None:
        return user
    return await get_by_email(db, cleaned)


async def register_customer(db: AsyncSession, payload: CustomerRegisterRequest) -> User:
    phone = payload.phone
    if await get_by_phone(db, phone):
        raise ConflictError("An account with this phone number already exists.")

    email: str | None = None
    if payload.email:
        email = str(payload.email).lower()
        if await get_by_email(db, email):
            raise ConflictError("An account with this email already exists.")

    user = User(
        full_name=payload.full_name.strip(),
        phone=phone,
        email=email,
        password_hash=hash_password(payload.password),
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    # Automatically associate previous guest orders placed with this phone number
    await db.execute(
        update(Order)
        .where(Order.user_id.is_(None), Order.phone == phone)
        .values(user_id=user.id)
    )

    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_customer(db: AsyncSession, identifier: str, password: str) -> User:
    user = await get_by_identifier(db, identifier)
    reference_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    password_ok = verify_password(password, reference_hash)

    if user is None or not password_ok or not user.is_active:
        logger.info("customer_login_failed", identifier=identifier.strip())
        raise AuthenticationError("Invalid phone/email or password.")

    user.last_login_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    return user


async def update_profile(
    db: AsyncSession, user: User, payload: CustomerProfileUpdate
) -> User:
    data = payload.model_dump(exclude_unset=True)

    if "phone" in data:
        new_phone = data["phone"]
        if new_phone and new_phone != user.phone:
            existing = await get_by_phone(db, new_phone)
            if existing is not None and existing.id != user.id:
                raise ConflictError("This phone number is already registered to another account.")
            user.phone = new_phone
            # Link guest orders with this new phone
            await db.execute(
                update(Order)
                .where(Order.user_id.is_(None), Order.phone == new_phone)
                .values(user_id=user.id)
            )
        elif new_phone is None:
            user.phone = None

    if "email" in data:
        new_email = data["email"]
        if new_email:
            new_email_clean = str(new_email).lower()
            if new_email_clean != user.email:
                existing = await get_by_email(db, new_email_clean)
                if existing is not None and existing.id != user.id:
                    raise ConflictError("This email is already registered to another account.")
                user.email = new_email_clean
        else:
            user.email = None

    if "full_name" in data and data["full_name"] is not None:
        user.full_name = str(data["full_name"]).strip()
    if "district" in data:
        user.district = data["district"]
    if "area" in data:
        user.area = data["area"]
    if "address" in data:
        user.address = data["address"]

    await db.commit()
    await db.refresh(user)
    return user


async def change_password(db: AsyncSession, user: User, current_pw: str, new_pw: str) -> None:
    if not verify_password(current_pw, user.password_hash):
        raise AuthenticationError("Current password is incorrect.")
    user.password_hash = hash_password(new_pw)
    await refresh_token_service.revoke_user_sessions(db, user.id)
    await audit_service.record(
        db,
        actor_id=user.id,
        action=AuditAction.PASSWORD_CHANGED,
        target_type="customer",
        target_id=user.id,
        metadata={"via": "customer_self", "phone": user.phone, "email": user.email},
    )
    await db.commit()
