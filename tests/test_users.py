from httpx import AsyncClient

from tests.conftest import TEST_PASSWORD

STAFF = {
    "email": "editor@implesia.com",
    "full_name": "Editor One",
    "password": "editor-passphrase",
    "role": "editor",
    "is_active": True,
}


async def _create(client: AsyncClient, headers: dict[str, str], **overrides: object) -> dict:
    payload = {**STAFF, **overrides}
    response = await client.post("/api/v1/users", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_superadmin_can_edit_and_delete_staff(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers)

    updated = await client.patch(
        f"/api/v1/users/{created['id']}",
        headers=auth_headers,
        json={
            "full_name": "Editor Updated",
            "email": "editor.updated@implesia.com",
            "role": "viewer",
            "is_active": False,
            "password": "replacement-passphrase",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["full_name"] == "Editor Updated"
    assert body["email"] == "editor.updated@implesia.com"
    assert body["role"] == "viewer"
    assert body["is_active"] is False

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "editor.updated@implesia.com", "password": "replacement-passphrase"},
    )
    assert login.status_code == 401

    deleted = await client.delete(f"/api/v1/users/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/users/{created['id']}", headers=auth_headers)
    assert missing.status_code == 404


async def test_duplicate_email_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await _create(client, auth_headers)
    second = await _create(
        client,
        auth_headers,
        email="second@implesia.com",
        full_name="Second",
    )
    response = await client.patch(
        f"/api/v1/users/{second['id']}",
        headers=auth_headers,
        json={"email": first["email"]},
    )
    assert response.status_code == 409


async def test_superadmin_cannot_lock_themselves_out(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    user_id = me.json()["id"]

    for payload in (
        {"role": "editor"},
        {"is_active": False},
    ):
        response = await client.patch(
            f"/api/v1/users/{user_id}", headers=auth_headers, json=payload
        )
        assert response.status_code == 403, response.text

    deleted = await client.delete(f"/api/v1/users/{user_id}", headers=auth_headers)
    assert deleted.status_code == 403

    still_there = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert still_there.status_code == 200
    assert still_there.json()["role"] == "superadmin"


async def test_another_superadmin_can_be_removed(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    extra = await _create(
        client,
        auth_headers,
        email="second.admin@implesia.com",
        full_name="Second Admin",
        role="superadmin",
        password="second-admin-passphrase",
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": extra["email"], "password": "second-admin-passphrase"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    me = await client.get("/api/v1/auth/me", headers=auth_headers)
    removed = await client.delete(f"/api/v1/users/{me.json()['id']}", headers=headers)
    assert removed.status_code == 204

    old_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@implesia.com", "password": TEST_PASSWORD},
    )
    assert old_login.status_code == 401
