import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]

# Authentication always uses this algorithm. It is not an environment setting.
JWT_ALGORITHM = "HS256"

# bcrypt silently truncates anything past 72 bytes, so reject it instead of
# accepting a password whose tail is never checked.
MAX_PASSWORD_BYTES = 72

# A real bcrypt hash ($2b$, 12 rounds) of a discarded random value. Missing
# accounts are checked against this so login does the same verify work as an
# account that exists. The plaintext is not stored.
DUMMY_PASSWORD_HASH = "$2b$12$MPrLrgS6SRSKcN8bAVKBR.Ge0Lhw4KAjXTZZBMYM3l5RI6wtSkleO"


class InvalidTokenError(Exception):
    """Raised when a JWT cannot be decoded or fails its expected claims."""


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except ValueError:
        return False


def _create_token(subject: str, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def create_access_token(subject: str) -> str:
    return _create_token(subject, "access", timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(subject: str, *, jti: str, family_id: str) -> tuple[str, datetime]:
    """Mint a refresh JWT whose ``jti`` and family id the caller has already chosen.

    The caller stores only a hash of ``jti``. ``family_id`` ties every rotation of
    one login together so a reused token can revoke the whole chain.
    """
    now = datetime.now(UTC)
    expires = now + timedelta(days=settings.refresh_token_expire_days)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": jti,
        "fam": family_id,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)
    return token, expires


def decode_token(
    token: str, expected_type: TokenType, *, verify_exp: bool = True
) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[JWT_ALGORITHM],
            options={"verify_exp": verify_exp},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("type") != expected_type:
        raise InvalidTokenError(f"Expected a {expected_type} token")
    if not payload.get("sub"):
        raise InvalidTokenError("Token is missing a subject")
    return payload
