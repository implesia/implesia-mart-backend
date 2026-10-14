"""IM-QA-013: access tokens carry the session id and are revoked with it."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.security import JWT_ALGORITHM, decode_token
from tests.conftest import TEST_PASSWORD

pytestmark = pytest.mark.usefixtures("superadmin_token")

LOGIN = {"email": "admin@implesia.com", "password": TEST_PASSWORD}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json=LOGIN)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_access_token_carries_the_refresh_family_as_sid(client: AsyncClient) -> None:
    body = await _login(client)
    access = decode_token(body["access_token"], "access")
    refresh = decode_token(body["refresh_token"], "refresh")
    assert access["sid"] == refresh["fam"]
    me = await client.get("/api/v1/auth/me", headers=_bearer(body["access_token"]))
    assert me.status_code == 200


async def test_logout_revokes_only_that_session(client: AsyncClient) -> None:
    first = await _login(client)
    second = await _login(client)

    out = await client.post("/api/v1/auth/logout", json={"refresh_token": first["refresh_token"]})
    assert out.status_code == 200

    revoked = await client.get("/api/v1/auth/me", headers=_bearer(first["access_token"]))
    assert revoked.status_code == 401
    assert revoked.json()["error"]["message"] == "Could not validate credentials"
    assert first["access_token"] not in revoked.text

    other = await client.get("/api/v1/auth/me", headers=_bearer(second["access_token"]))
    assert other.status_code == 200
    still = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert still.status_code == 200


async def test_access_token_survives_rotation_within_the_same_session(
    client: AsyncClient,
) -> None:
    body = await _login(client)
    rotated = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert rotated.status_code == 200
    new = rotated.json()
    # Same session: the access token minted before rotation keeps working.
    assert (
        await client.get("/api/v1/auth/me", headers=_bearer(body["access_token"]))
    ).status_code == 200
    assert (
        await client.get("/api/v1/auth/me", headers=_bearer(new["access_token"]))
    ).status_code == 200


async def test_refresh_reuse_revokes_the_family_and_its_access_tokens(client: AsyncClient) -> None:
    body = await _login(client)
    rotated = (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    ).json()

    reused = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert reused.status_code == 401
    assert reused.json()["error"]["message"] == "Invalid refresh token"

    for token in (body["access_token"], rotated["access_token"]):
        assert (await client.get("/api/v1/auth/me", headers=_bearer(token))).status_code == 401
    after = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert after.status_code == 401


async def test_revoked_refresh_token_is_rejected_after_logout(client: AsyncClient) -> None:
    body = await _login(client)
    await client.post("/api/v1/auth/logout", json={"refresh_token": body["refresh_token"]})
    again = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert again.status_code == 401


async def test_anonymous_and_unbound_tokens_are_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/admin/home/banner")).status_code == 401

    body = await _login(client)
    sub = decode_token(body["access_token"], "access")["sub"]
    now = datetime.now(UTC)
    claims = {
        "sub": sub,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    legacy = jwt.encode(claims, settings.secret_key, algorithm=JWT_ALGORITHM)
    assert (await client.get("/api/v1/auth/me", headers=_bearer(legacy))).status_code == 401

    unknown = jwt.encode(
        {**claims, "sid": str(uuid.uuid4())}, settings.secret_key, algorithm=JWT_ALGORITHM
    )
    response = await client.get("/api/v1/auth/me", headers=_bearer(unknown))
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Could not validate credentials"
