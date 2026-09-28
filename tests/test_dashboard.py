from httpx import AsyncClient


async def test_dashboard_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/dashboard")
    assert anonymous.status_code == 401

    allowed = await client.get("/api/v1/admin/dashboard", headers=auth_headers)
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["users_total"] >= 1
    assert body["users_active"] >= 1

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "viewer@implesia.com",
            "full_name": "Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.get(
        "/api/v1/admin/dashboard",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403


async def test_editor_can_read_the_dashboard(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "editor@implesia.com",
            "full_name": "Editor",
            "password": "editor-passphrase",
            "role": "editor",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "editor@implesia.com", "password": "editor-passphrase"},
    )
    response = await client.get(
        "/api/v1/admin/dashboard",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["users_total"] >= 2
