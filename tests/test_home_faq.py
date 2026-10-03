from httpx import AsyncClient

SEEDED = [
    "আমার অর্ডার কীভাবে ট্র্যাক করব?",
    "অর্ডারের জন্য কি আগে টাকা পরিশোধ করতে হবে?",
    "প্রোডাক্ট পছন্দ না হলে রিটার্ন করা যাবে?",
    "কোনো সমস্যা হলে কীভাবে যোগাযোগ করব?",
    "প্রোডাক্টগুলো কি কোয়ালিটি চেক করা হয়?",
    "ডেলিভারি পেতে কত সময় লাগে?",
]


async def test_public_faq_seeds_the_home_questions(client: AsyncClient) -> None:
    response = await client.get("/api/v1/home/faq")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kicker"] == "জিজ্ঞাসা ও উত্তর"
    assert body["title"] == "প্রায়শই জিজ্ঞাসিত প্রশ্ন"
    assert body["more_label"] == "আরও প্রশ্ন দেখুন"
    assert body["more_href"] == "/faqs"
    assert [item["question"] for item in body["items"]] == SEEDED
    assert body["items"][0]["category"] == "অর্ডার ট্র্যাকিং"
    assert "is_active" not in body["items"][0]


async def test_faq_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/home/faq")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "faq-viewer@implesia.com",
            "full_name": "FAQ Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "faq-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/home/faq/items",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"question": "Nope", "answer": "Nope"},
    )
    assert denied.status_code == 403


async def test_editor_can_create_reorder_hide_and_remove_a_question(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.services.home import faq_service

    monkeypatch.setattr(faq_service, "MAX_ITEMS", 6)
    blocked = await client.post(
        "/api/v1/admin/home/faq/items",
        headers=auth_headers,
        json={"question": "Extra", "answer": "Extra"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can show up to 24 questions"
    monkeypatch.setattr(faq_service, "MAX_ITEMS", 24)

    created = await client.post(
        "/api/v1/admin/home/faq/items",
        headers=auth_headers,
        json={
            "category": "  টেস্ট  ",
            "question": "  Checked?  ",
            "answer": "  উত্তর।  ",
            "is_active": False,
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["category"] == "টেস্ট"
    assert item["question"] == "Checked?"
    assert item["answer"] == "উত্তর।"
    assert item["is_active"] is False

    public = await client.get("/api/v1/home/faq")
    assert [entry["question"] for entry in public.json()["items"]] == SEEDED

    listed = await client.get("/api/v1/admin/home/faq", headers=auth_headers)
    ids = [entry["id"] for entry in listed.json()["items"]]
    moved = await client.put(
        "/api/v1/admin/home/faq/items/order",
        headers=auth_headers,
        json={"ids": [item["id"], *ids[:-1]]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["items"][0]["id"] == item["id"]

    incomplete = await client.put(
        "/api/v1/admin/home/faq/items/order",
        headers=auth_headers,
        json={"ids": [item["id"]]},
    )
    assert incomplete.status_code == 422

    blank = await client.post(
        "/api/v1/admin/home/faq/items",
        headers=auth_headers,
        json={"question": "   ", "answer": "উত্তর"},
    )
    assert blank.status_code == 422

    bad_link = await client.patch(
        "/api/v1/admin/home/faq",
        headers=auth_headers,
        json={
            "kicker": "জিজ্ঞাসা ও উত্তর",
            "title": "প্রায়শই জিজ্ঞাসিত প্রশ্ন",
            "subtitle": "অর্ডার, পেমেন্ট, ডেলিভারি ও রিটার্ন নিয়ে সাধারণ প্রশ্নের দ্রুত উত্তর।",
            "more_label": "আরও প্রশ্ন দেখুন",
            "more_href": "nope",
        },
    )
    assert bad_link.status_code == 422

    blank_link = await client.patch(
        "/api/v1/admin/home/faq",
        headers=auth_headers,
        json={
            "kicker": "জিজ্ঞাসা",
            "title": "প্রশ্ন",
            "subtitle": "",
            "more_label": "",
            "more_href": "",
        },
    )
    assert blank_link.status_code == 200, blank_link.text
    assert blank_link.json()["more_href"] == "/faqs"
    assert blank_link.json()["kicker"] == "জিজ্ঞাসা"

    removed = await client.delete(
        f"/api/v1/admin/home/faq/items/{item['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Question removed"

    again = await client.get("/api/v1/home/faq")
    assert [entry["question"] for entry in again.json()["items"]] == SEEDED
