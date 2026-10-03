from httpx import AsyncClient


def _item(
    *,
    question: str = "When do you reply?",
    answer: str = "During working hours.",
    active: bool = True,
) -> dict:
    return {"question": question, "answer": answer, "is_active": active}


def _body(
    *,
    active: bool = True,
    title: str = "Questions",
    question: str = "When do you reply?",
) -> dict:
    return {
        "is_active": active,
        "title": title,
        "subtitle": "Short answers.",
        "items": [_item(question=question)],
    }


async def test_public_contact_faq_starts_without_seed_copy(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/contact/faq")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == ""
    assert body["items"] == []
    assert "is_active" not in body
    assert "যোগাযোগ নিয়ে সাধারণ প্রশ্ন" not in response.text


async def test_contact_faq_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/contact/faq")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "contact-faq-viewer@implesia.com",
            "full_name": "Contact FAQ Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "contact-faq-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/pages/contact/faq",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json=_body(active=False),
    )
    assert denied.status_code == 403


async def test_editor_saves_hides_and_restores_the_contact_faq(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    blank = await client.patch(
        "/api/v1/admin/pages/contact/faq",
        headers=auth_headers,
        json=_body(title="   "),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    incomplete = await client.patch(
        "/api/v1/admin/pages/contact/faq",
        headers=auth_headers,
        json=_body(question=" "),
    )
    assert incomplete.status_code == 422
    message = "Each question needs a question and an answer."
    assert incomplete.json()["error"]["message"] == message

    saved = await client.patch(
        "/api/v1/admin/pages/contact/faq",
        headers=auth_headers,
        json={
            **_body(),
            "items": [_item(), _item(question="Hidden?", answer="No.", active=False)],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_active"] is True
    assert len(saved.json()["items"]) == 2

    shown = (await client.get("/api/v1/pages/contact/faq")).json()
    assert shown["title"] == "Questions"
    assert len(shown["items"]) == 1
    assert shown["items"][0]["question"] == "When do you reply?"
    assert "is_active" not in shown

    hidden = await client.patch(
        "/api/v1/admin/pages/contact/faq",
        headers=auth_headers,
        json=_body(active=False),
    )
    assert hidden.status_code == 200
    assert (await client.get("/api/v1/pages/contact/faq")).json()["title"] == ""

    restored = await client.patch(
        "/api/v1/admin/pages/contact/faq",
        headers=auth_headers,
        json=_body(active=True),
    )
    assert restored.status_code == 200
    assert (await client.get("/api/v1/pages/contact/faq")).json()["title"] == "Questions"
