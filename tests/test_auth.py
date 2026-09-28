from httpx import AsyncClient

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
