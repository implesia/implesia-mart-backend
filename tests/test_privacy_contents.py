from httpx import AsyncClient


def _body(
    *,
    active: bool = True,
    title: str = "On this page",
    subtitle: str = "Jump to a topic",
    nav_label: str = "Sections",
) -> dict:
    return {
        "is_active": active,
        "title": title,
        "subtitle": subtitle,
        "nav_label": nav_label,
    }


async def test_public_privacy_contents_start_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/privacy/contents")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["subtitle"] == ""
    assert body["nav_label"] == ""
    assert "is_active" not in body
    assert "নীতিমালা" not in response.text
    assert "সর্বশেষ আপডেট: সেপ্টেম্বর ২০২৬" not in response.text
    assert "গোপনীয়তা সেকশন" not in response.text


async def test_privacy_contents_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/privacy/contents")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "privacy-contents-viewer@implesia.com",
            "full_name": "Privacy Contents Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "privacy-contents-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/privacy/contents",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_clears_the_privacy_contents(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.patch(
        "/api/v1/admin/pages/privacy/contents",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["title"] == "On this page"
    assert saved.json()["nav_label"] == "Sections"

    public = await client.get("/api/v1/pages/privacy/contents")
    assert public.json()["title"] == "On this page"
    assert public.json()["subtitle"] == "Jump to a topic"
    assert "is_active" not in public.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/privacy/contents",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200, hidden.text
    cleared = await client.get("/api/v1/pages/privacy/contents")
    assert cleared.json()["title"] == ""
    assert cleared.json()["nav_label"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/privacy/contents",
        headers=auth_headers,
        json=_body(title="", subtitle="", nav_label=""),
    )
    assert restored.status_code == 200, restored.text
    shown = await client.get("/api/v1/pages/privacy/contents")
    assert shown.json() == {"title": "", "subtitle": "", "nav_label": ""}
