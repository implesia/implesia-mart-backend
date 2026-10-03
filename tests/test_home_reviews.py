import json

from httpx import AsyncClient

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)

SEEDED = [
    "সানসেট ল্যাম্প",
    "AI ফোন হোল্ডার",
    "কাস্টম গাউন",
    "AI ফোন হোল্ডার",
    "সানসেট ল্যাম্প",
    "বেবি পার্টি ফ্রক",
]


def _parts(
    body: dict, image: tuple[str, bytes, str] | None = None
) -> list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]]:
    parts: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
        ("payload", (None, json.dumps(body)))
    ]
    if image is not None:
        parts.append(("image", image))
    return parts


async def test_public_reviews_seed_the_home_row(client: AsyncClient) -> None:
    response = await client.get("/api/v1/home/reviews")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kicker"] == "রিভিউ"
    assert body["title"] == "কাস্টমাররা যা বলছেন"
    assert [item["product"] for item in body["items"]] == SEEDED
    assert body["items"][1]["channel"] == "Messenger"
    assert body["items"][0]["image_src"] == "/images/reviews/sunset-lamp-1.jpg"
    assert "is_active" not in body["items"][0]


async def test_review_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/home/reviews")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "review-viewer@implesia.com",
            "full_name": "Review Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "review-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/home/reviews/items",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        files=_parts({"product": "Nope"}),
    )
    assert denied.status_code == 403


async def test_editor_can_create_reorder_hide_and_remove_a_review(
    client: AsyncClient, auth_headers: dict[str, str], tmp_path, monkeypatch
) -> None:
    from app.core.config import settings
    from app.services.home import review_service

    monkeypatch.setattr(settings, "media_root", tmp_path)
    monkeypatch.setattr(review_service, "MAX_ITEMS", 6)
    blocked = await client.post(
        "/api/v1/admin/home/reviews/items",
        headers=auth_headers,
        files=_parts({"product": "Extra"}),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can show up to 24 reviews"
    monkeypatch.setattr(review_service, "MAX_ITEMS", 24)

    created = await client.post(
        "/api/v1/admin/home/reviews/items",
        headers=auth_headers,
        files=_parts(
            {
                "product": "  Checked  ",
                "channel": "Messenger",
                "image_alt": "  স্ক্রিনশট  ",
                "is_active": False,
            },
            ("review.jpg", JPEG, "image/jpeg"),
        ),
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["product"] == "Checked"
    assert item["channel"] == "Messenger"
    assert item["image_alt"] == "স্ক্রিনশট"
    assert item["is_active"] is False
    assert item["image_src"].startswith("/media/reviews/")
    stored = tmp_path / "reviews" / item["image_src"].removeprefix("/media/reviews/")
    assert stored.is_file()

    public = await client.get("/api/v1/home/reviews")
    names = [entry["product"] for entry in public.json()["items"]]
    assert "Checked" not in names
    assert names == SEEDED

    listed = await client.get("/api/v1/admin/home/reviews", headers=auth_headers)
    ids = [entry["id"] for entry in listed.json()["items"]]
    moved = await client.put(
        "/api/v1/admin/home/reviews/items/order",
        headers=auth_headers,
        json={"ids": [item["id"], *ids[:-1]]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["items"][0]["id"] == item["id"]

    incomplete = await client.put(
        "/api/v1/admin/home/reviews/items/order",
        headers=auth_headers,
        json={"ids": [item["id"]]},
    )
    assert incomplete.status_code == 422

    blank = await client.post(
        "/api/v1/admin/home/reviews/items",
        headers=auth_headers,
        files=_parts({"product": "   "}),
    )
    assert blank.status_code == 422

    staged = await client.post(
        "/api/v1/admin/home/reviews/items",
        headers=auth_headers,
        files=_parts({"product": "Local", "image_src": "/uploads/review.jpg"}),
    )
    assert staged.status_code == 422

    removed = await client.delete(
        f"/api/v1/admin/home/reviews/items/{item['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Review removed"
    assert not stored.is_file()

    again = await client.get("/api/v1/home/reviews")
    assert [entry["product"] for entry in again.json()["items"]] == SEEDED
