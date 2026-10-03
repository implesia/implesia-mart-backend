import json

from httpx import AsyncClient

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
LAMP = "/images/products/lamp/lamp-2.jpg"
FROCK = "/images/products/baby-products/baby-frock-with-baby.jpeg"
TITLE = "কোয়ালিটি এখন বিলাসিতা নয়, দায়িত্ব"


def _parts(
    body: dict, image_0: tuple[str, bytes, str] | None = None
) -> list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]]:
    parts: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
        ("payload", (None, json.dumps(body)))
    ]
    if image_0 is not None:
        parts.append(("image_0", image_0))
    return parts


def _seed_body(**overrides: object) -> dict:
    body = {
        "eyebrow": "আমাদের দৃষ্টিভঙ্গি",
        "title": TITLE,
        "body": "Seed body",
        "quote": "কোয়ালিটি একটি অভ্যাস, একবারের কাজ নয়।",
        "images": [
            {"alt": "সানসেট ল্যাম্প — কোয়ালিটি চেক করা প্রোডাক্ট", "src": LAMP, "is_active": True},
            {"alt": "হাতে তৈরি বেবি পার্টি ফ্রক", "src": FROCK, "is_active": True},
        ],
    }
    body.update(overrides)
    return body


async def test_public_sustainability_origin_seeds_the_block(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/sustainability/origin")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eyebrow"] == "আমাদের দৃষ্টিভঙ্গি"
    assert body["title"] == TITLE
    assert body["quote"] == "কোয়ালিটি একটি অভ্যাস, একবারের কাজ নয়।"
    assert [image["src"] for image in body["images"]] == [LAMP, FROCK]
    assert "is_active" not in body["images"][0]


async def test_sustainability_origin_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/sustainability/origin")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "sustain-origin-viewer@implesia.com",
            "full_name": "Sustain Origin Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "sustain-origin-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.put(
        "/api/v1/admin/pages/sustainability/origin",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        files=_parts(_seed_body(title="Nope")),
    )
    assert denied.status_code == 403


async def test_editor_can_hide_upload_and_restore_photos(
    client: AsyncClient, auth_headers: dict[str, str], tmp_path, monkeypatch
) -> None:
    from app.core.config import settings
    from app.services.sustainability import origin_service

    monkeypatch.setattr(settings, "media_root", tmp_path)
    monkeypatch.setattr(origin_service, "MAX_PHOTOS", 2)
    blocked = await client.put(
        "/api/v1/admin/pages/sustainability/origin",
        headers=auth_headers,
        files=_parts(
            _seed_body(
                images=[
                    {"alt": "One", "src": LAMP},
                    {"alt": "Two", "src": FROCK},
                    {"alt": "Three", "src": LAMP},
                ]
            )
        ),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can add up to 12 photos"
    monkeypatch.setattr(origin_service, "MAX_PHOTOS", 12)

    blank = await client.put(
        "/api/v1/admin/pages/sustainability/origin",
        headers=auth_headers,
        files=_parts(_seed_body(title="   ")),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    staged = await client.put(
        "/api/v1/admin/pages/sustainability/origin",
        headers=auth_headers,
        files=_parts(_seed_body(images=[{"alt": "Left", "src": "blob:origin"}])),
    )
    assert staged.status_code == 422
    assert staged.json()["error"]["message"] == "Send the image file with the point of view"

    empty = await client.put(
        "/api/v1/admin/pages/sustainability/origin",
        headers=auth_headers,
        files=_parts(_seed_body(images=[{"alt": "Left", "src": ""}])),
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["message"] == "Add an image, or remove the empty photo."

    hidden = await client.put(
        "/api/v1/admin/pages/sustainability/origin",
        headers=auth_headers,
        files=_parts(
            _seed_body(
                images=[
                    {"alt": "Lamp", "src": LAMP, "is_active": True},
                    {"alt": "Frock", "src": FROCK, "is_active": False},
                ]
            )
        ),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["images"][1]["is_active"] is False
    public = await client.get("/api/v1/pages/sustainability/origin")
    assert [image["src"] for image in public.json()["images"]] == [LAMP]

    uploaded = await client.put(
        "/api/v1/admin/pages/sustainability/origin",
        headers=auth_headers,
        files=_parts(
            _seed_body(images=[{"alt": "Upload", "src": ""}, {"alt": "Frock", "src": FROCK}]),
            ("origin.jpg", JPEG, "image/jpeg"),
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    stored = uploaded.json()["images"][0]["src"]
    assert stored.startswith("/media/sustainability/")
    assert (tmp_path / stored.removeprefix("/media/")).is_file()

    restored = await client.put(
        "/api/v1/admin/pages/sustainability/origin",
        headers=auth_headers,
        files=_parts(_seed_body()),
    )
    assert restored.status_code == 200, restored.text
    assert [image["src"] for image in restored.json()["images"]] == [LAMP, FROCK]
    assert not (tmp_path / stored.removeprefix("/media/")).exists()

    public = await client.get("/api/v1/pages/sustainability/origin")
    assert public.json()["title"] == TITLE
    assert [image["src"] for image in public.json()["images"]] == [LAMP, FROCK]
