from httpx import AsyncClient


def _social(href: str = "") -> list[dict]:
    return [
        {"platform": "facebook", "label": "Facebook", "href": href, "is_active": True},
        {"platform": "linkedin", "label": "LinkedIn", "href": "", "is_active": True},
    ]


def _channel(*, href: str = "tel:+8801000000000", active: bool = True) -> dict:
    return {
        "icon": "call",
        "title": "Call",
        "value": "+880 1000-000000",
        "href": href,
        "is_active": active,
    }


def _body(
    *,
    active: bool = True,
    title: str = "Contacts",
    href: str = "tel:+8801000000000",
) -> dict:
    return {
        "is_active": active,
        "title": title,
        "subtitle": "Reach us any way you like.",
        "badge": "",
        "channels": [_channel(href=href)],
        "social": _social(),
    }


async def test_public_contact_details_start_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/contact/details")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["channels"] == []
    assert body["social"] == []
    assert "is_active" not in body
    assert "সরাসরি যোগাযোগ" not in response.text
    assert "implesiamart" not in response.text


async def test_contact_details_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/contact/details")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "contact-details-viewer@implesia.com",
            "full_name": "Contact Details Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "contact-details-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/contact/details",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_contact_details(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/contact/details",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    incomplete = await client.patch(
        "/api/v1/admin/pages/contact/details",
        headers=auth_headers,
        json=_body(href=" "),
    )
    assert incomplete.status_code == 422
    message = "Each channel needs a title, a value, and a link."
    assert incomplete.json()["error"]["message"] == message

    blocked = await client.patch(
        "/api/v1/admin/pages/contact/details",
        headers=auth_headers,
        json=_body(href="javascript:alert(1)"),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "Channel link is not allowed"

    saved = await client.patch(
        "/api/v1/admin/pages/contact/details",
        headers=auth_headers,
        json={
            **_body(),
            "channels": [_channel(), _channel(href="mailto:desk@example.com", active=False)],
            "social": _social("https://example.com/facebook"),
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_active"] is True
    assert len(saved.json()["channels"]) == 2
    assert saved.json()["social"][0]["platform"] == "facebook"

    visible = await client.get("/api/v1/pages/contact/details")
    shown = visible.json()
    assert shown["title"] == "Contacts"
    assert len(shown["channels"]) == 1
    assert "is_active" not in shown
    assert shown["channels"][0]["href"] == "tel:+8801000000000"
    assert shown["social"][0]["href"] == "https://example.com/facebook"
    assert len(shown["social"]) == 1

    hidden = await client.patch(
        "/api/v1/admin/pages/contact/details",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200
    assert (await client.get("/api/v1/pages/contact/details")).json()["title"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/contact/details",
        headers=auth_headers,
        json=_body(active=True),
    )
    assert restored.status_code == 200
    assert (await client.get("/api/v1/pages/contact/details")).json()["title"] == "Contacts"
