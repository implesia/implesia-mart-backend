from httpx import AsyncClient


def _hour(*, label: str = "Saturday", value: str = "9:00 – 22:00", active: bool = True) -> dict:
    return {"label": label, "value": value, "is_active": active}


def _link(*, href: str = "/faqs", active: bool = True) -> dict:
    return {"icon": "help", "label": "Questions", "href": href, "is_active": active}


def _body(*, active: bool = True, title: str = "Support", href: str = "/faqs") -> dict:
    return {
        "is_active": active,
        "title": title,
        "subtitle": "When we answer.",
        "hours": [_hour()],
        "quick_links": [_link(href=href)],
    }


async def test_public_contact_support_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/contact/support")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["hours"] == []
    assert body["quick_links"] == []
    assert "is_active" not in body
    assert "সাপোর্ট সময়সূচি" not in response.text


async def test_contact_support_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/contact/support")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "contact-support-viewer@implesia.com",
            "full_name": "Contact Support Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "contact-support-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/contact/support",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_contact_support(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/contact/support",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    missing_hours = await client.patch(
        "/api/v1/admin/pages/contact/support",
        headers=auth_headers,
        json={**_body(), "hours": [_hour(label=" ")]},
    )
    assert missing_hours.status_code == 422
    assert missing_hours.json()["error"]["message"] == "Each row needs a day and the hours."

    missing_link = await client.patch(
        "/api/v1/admin/pages/contact/support",
        headers=auth_headers,
        json=_body(href=" "),
    )
    assert missing_link.status_code == 422
    assert missing_link.json()["error"]["message"] == "Each link needs a label and a destination."

    blocked = await client.patch(
        "/api/v1/admin/pages/contact/support",
        headers=auth_headers,
        json=_body(href="javascript:alert(1)"),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "Link is not allowed"

    saved = await client.patch(
        "/api/v1/admin/pages/contact/support",
        headers=auth_headers,
        json={
            **_body(),
            "hours": [_hour(), _hour(label="Friday", active=False)],
            "quick_links": [_link(), _link(href="https://example.com/help")],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_active"] is True
    assert len(saved.json()["hours"]) == 2

    shown = (await client.get("/api/v1/pages/contact/support")).json()
    assert shown["title"] == "Support"
    assert len(shown["hours"]) == 1
    assert len(shown["quick_links"]) == 2
    assert "is_active" not in shown

    hidden = await client.patch(
        "/api/v1/admin/pages/contact/support",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200
    assert (await client.get("/api/v1/pages/contact/support")).json()["title"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/contact/support",
        headers=auth_headers,
        json=_body(active=True),
    )
    assert restored.status_code == 200
    assert (await client.get("/api/v1/pages/contact/support")).json()["title"] == "Support"
