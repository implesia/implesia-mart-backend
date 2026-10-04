import base64
import json
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import DUMMY_PASSWORD_HASH, InvalidTokenError, decode_token
from app.models.refresh_token import RefreshToken
from app.services.refresh_token_service import hash_jti
from tests.conftest import TEST_PASSWORD


async def test_login_returns_token_pair(client: AsyncClient, superadmin_token: str) -> None:
    assert superadmin_token


async def test_login_with_wrong_password_is_rejected(
    client: AsyncClient, superadmin_token: str
) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": "wrong-password-entirely"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.json()["error"]["message"] == "Invalid email or password."


def _unsigned(header: dict[str, str], payload: dict[str, str]) -> str:
    def part(value: dict[str, str]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{part(header)}.{part(payload)}."


def test_decoder_accepts_only_hs256() -> None:
    future = datetime.now(UTC) + timedelta(minutes=5)
    other = jwt.encode(
        {"sub": "user", "type": "access", "exp": future},
        "a" * 48,
        algorithm="HS384",
    )
    with pytest.raises(InvalidTokenError):
        decode_token(other, "access")

    unsigned = _unsigned({"alg": "none", "typ": "JWT"}, {"sub": "user", "type": "access"})
    with pytest.raises(InvalidTokenError):
        decode_token(unsigned, "access")


def test_dummy_hash_is_a_bcrypt_verify_target() -> None:
    assert DUMMY_PASSWORD_HASH.startswith("$2b$12$")
    assert bcrypt.checkpw(b"wrong-password-entirely", DUMMY_PASSWORD_HASH.encode()) is False


async def test_missing_account_does_not_generate_a_hash(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(password: str) -> str:
        raise AssertionError(password)

    monkeypatch.setattr("app.services.user_service.hash_password", fail)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@implesia.com", "password": "wrong-password-entirely"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password."


async def test_login_failures_look_the_same(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "disabled@implesia.com",
            "full_name": "Disabled Staff",
            "password": "disabled-account-pass",
            "role": "viewer",
            "is_active": False,
        },
    )
    assert created.status_code == 201, created.text

    missing = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@implesia.com", "password": "wrong-password-entirely"},
    )
    wrong = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": "wrong-password-entirely"},
    )
    disabled = await client.post(
        "/api/v1/auth/login",
        json={"email": "disabled@implesia.com", "password": "disabled-account-pass"},
    )
    expected = {
        "error": {
            "code": "unauthenticated",
            "message": "Invalid email or password.",
            "details": None,
        }
    }
    assert missing.status_code == wrong.status_code == disabled.status_code == 401
    assert missing.json() == wrong.json() == disabled.json() == expected
    assert "disabled" not in missing.text


async def test_me_returns_current_user(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "admin@implesia.com"
    assert body["role"] == "superadmin"


async def test_me_requires_a_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_refresh_issues_a_new_access_token(
    client: AsyncClient, superadmin_token: str
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    refresh_token = login.json()["refresh_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_access_token_is_not_accepted_as_refresh_token(
    client: AsyncClient, superadmin_token: str
) -> None:
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": superadmin_token})
    assert response.status_code == 401


async def test_a_used_refresh_token_cannot_mint_another_session(
    client: AsyncClient, superadmin_token: str
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    first = login.json()["refresh_token"]
    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert rotated.status_code == 200, rotated.text
    second = rotated.json()["refresh_token"]
    assert second != first

    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert reused.status_code == 401

    killed = await client.post("/api/v1/auth/refresh", json={"refresh_token": second})
    assert killed.status_code == 401


async def test_logout_revokes_the_refresh_family(
    client: AsyncClient, superadmin_token: str
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    body = login.json()
    logged_out = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": body["refresh_token"]}
    )
    assert logged_out.status_code == 200
    assert logged_out.json()["message"] == "Signed out"

    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert refreshed.status_code == 401
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200


async def test_password_change_revokes_refresh_sessions(
    client: AsyncClient, superadmin_token: str
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    body = login.json()
    changed = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {body['access_token']}"},
        json={"current_password": TEST_PASSWORD, "new_password": "replacement-passphrase"},
    )
    assert changed.status_code == 200, changed.text

    refreshed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert refreshed.status_code == 401

    again = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": "replacement-passphrase"},
    )
    assert again.status_code == 200, again.text


async def test_refresh_jti_is_stored_as_a_hash(
    client: AsyncClient, db_session: AsyncSession, superadmin_token: str
) -> None:
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    token = login.json()["refresh_token"]
    payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256"])
    rows = (await db_session.execute(select(RefreshToken))).scalars().all()
    assert rows
    assert payload["jti"] not in {row.jti_hash for row in rows}
    assert hash_jti(payload["jti"]) in {row.jti_hash for row in rows}
