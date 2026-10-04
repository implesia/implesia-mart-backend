import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import TokenPair


def hash_jti(jti: str) -> str:
    return hashlib.sha256(jti.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _pair(user_id: uuid.UUID, refresh_token: str) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(str(user_id)),
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


def _claims(raw: str) -> dict[str, str]:
    try:
        payload = decode_token(raw, expected_type="refresh")
        jti = payload.get("jti")
        family = payload.get("fam")
        subject = payload.get("sub")
        if not isinstance(jti, str) or not isinstance(family, str) or not isinstance(subject, str):
            raise InvalidTokenError("Refresh token is missing its session id")
        uuid.UUID(subject)
        uuid.UUID(family)
    except (InvalidTokenError, ValueError) as exc:
        raise AuthenticationError("Invalid refresh token") from exc
    return {"jti": jti, "fam": family, "sub": subject}


async def _lock_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    statement = select(RefreshToken.id).where(RefreshToken.family_id == family_id)
    bind = db.get_bind()
    if bind is not None and bind.dialect.name != "sqlite":
        statement = statement.with_for_update()
    await db.execute(statement)


async def _revoke_family(db: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def _family_has_rows(db: AsyncSession, family_id: uuid.UUID) -> bool:
    found = await db.scalar(
        select(RefreshToken.id).where(RefreshToken.family_id == family_id).limit(1)
    )
    return found is not None


async def revoke_user_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Mark every live refresh token for this user revoked. The caller commits."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def _remember(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    jti: str,
    expires_at: datetime,
) -> None:
    db.add(
        RefreshToken(
            user_id=user_id,
            family_id=family_id,
            jti_hash=hash_jti(jti),
            expires_at=expires_at,
        )
    )


async def issue_session(db: AsyncSession, user: User) -> TokenPair:
    family_id = uuid.uuid4()
    jti = uuid.uuid4().hex
    token, expires_at = create_refresh_token(str(user.id), jti=jti, family_id=str(family_id))
    _remember(db, user_id=user.id, family_id=family_id, jti=jti, expires_at=expires_at)
    await db.commit()
    return _pair(user.id, token)


async def rotate_session(db: AsyncSession, raw: str) -> TokenPair:
    claims = _claims(raw)
    user_id = uuid.UUID(claims["sub"])
    family_id = uuid.UUID(claims["fam"])
    now = datetime.now(UTC)
    await _lock_family(db, family_id)
    current = await db.scalar(
        select(RefreshToken).where(RefreshToken.jti_hash == hash_jti(claims["jti"]))
    )
    reusable = (
        current is not None
        and current.user_id == user_id
        and current.family_id == family_id
        and current.revoked_at is None
        and _as_utc(current.expires_at) > now
    )
    if current is None or not reusable:
        await _reject_reuse(db, current, family_id, now)
        raise AuthenticationError("Invalid refresh token")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        await _revoke_family(db, family_id, now)
        await db.commit()
        raise AuthenticationError("Invalid refresh token")

    current.revoked_at = now
    jti = uuid.uuid4().hex
    token, expires_at = create_refresh_token(str(user_id), jti=jti, family_id=str(family_id))
    _remember(db, user_id=user_id, family_id=family_id, jti=jti, expires_at=expires_at)
    await db.commit()
    return _pair(user_id, token)


async def _reject_reuse(
    db: AsyncSession,
    current: RefreshToken | None,
    family_id: uuid.UUID,
    now: datetime,
) -> None:
    families: set[uuid.UUID] = set()
    if current is not None:
        families.add(current.family_id)
    if await _family_has_rows(db, family_id):
        families.add(family_id)
    if not families:
        return
    for family in families:
        await _revoke_family(db, family, now)
    await db.commit()


async def logout_session(db: AsyncSession, raw: str) -> None:
    claims = _claims(raw)
    user_id = uuid.UUID(claims["sub"])
    family_id = uuid.UUID(claims["fam"])
    await _lock_family(db, family_id)
    current = await db.scalar(
        select(RefreshToken).where(RefreshToken.jti_hash == hash_jti(claims["jti"]))
    )
    if current is None or current.user_id != user_id or current.family_id != family_id:
        raise AuthenticationError("Invalid refresh token")
    await _revoke_family(db, family_id, datetime.now(UTC))
    await db.commit()
