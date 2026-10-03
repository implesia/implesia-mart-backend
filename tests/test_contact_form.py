from httpx import AsyncClient

TITLE = "মেসেজ পাঠান"


def _field(label: str, placeholder: str = "") -> dict:
    return {"label": label, "placeholder": placeholder}


def _body(*, active: bool = True, title: str = TITLE, name_label: str = "নাম") -> dict:
    return {
        "is_active": active,
        "title": title,
        "subtitle": "ফর্ম পূরণ করলে হোয়াটসঅ্যাপে খুলবে।",
        "cta": "হোয়াটসঅ্যাপে পাঠান",
        "hint": "বাইরে হোয়াটসঅ্যাপ খুলবে।",
        "fields": {
            "name": _field(name_label, "আপনার নাম লিখুন"),
            "phone": _field("ফোন নাম্বার", "০১XXX-XXXXXX"),
            "subject": _field("বিষয়", "যেমন: অর্ডার সম্পর্কে জানতে চাই"),
            "message": _field("মেসেজ", "আমরা কীভাবে সাহায্য করতে পারি লিখুন..."),
        },
    }


async def test_public_contact_form_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/contact/form")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["cta"] == ""
    assert body["fields"]["name"]["label"] == ""
    assert body["fields"]["message"]["placeholder"] == ""
    assert "is_active" not in body
    assert TITLE not in response.text


async def test_contact_form_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/contact/form")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "contact-form-viewer@implesia.com",
            "full_name": "Contact Form Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "contact-form-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/contact/form",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_the_contact_form(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/contact/form",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    missing_label = await client.patch(
        "/api/v1/admin/pages/contact/form",
        headers=auth_headers,
        json=_body(name_label="  "),
    )
    assert missing_label.status_code == 422
    assert missing_label.json()["error"]["message"] == "Each field needs a label."

    missing_button = await client.patch(
        "/api/v1/admin/pages/contact/form",
        headers=auth_headers,
        json={**_body(), "cta": " "},
    )
    assert missing_button.status_code == 422
    assert missing_button.json()["error"]["message"] == "Button label is required."

    saved = await client.patch(
        "/api/v1/admin/pages/contact/form",
        headers=auth_headers,
        json=_body(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_active"] is True
    assert saved.json()["fields"]["phone"]["label"] == "ফোন নাম্বার"

    visible = await client.get("/api/v1/pages/contact/form")
    assert visible.json()["title"] == TITLE
    assert "is_active" not in visible.json()

    hidden = await client.patch(
        "/api/v1/admin/pages/contact/form",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200
    assert hidden.json()["is_active"] is False
    public = await client.get("/api/v1/pages/contact/form")
    assert public.json()["title"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/contact/form",
        headers=auth_headers,
        json=_body(active=True),
    )
    assert restored.status_code == 200
    assert (await client.get("/api/v1/pages/contact/form")).json()["title"] == TITLE
