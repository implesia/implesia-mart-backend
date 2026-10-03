import json

from httpx import AsyncClient

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
PHOTO = "/images/products/baby-products/3-quater-ground-frog.jpeg"
TITLE = "দীর্ঘস্থায়ী প্রোডাক্ট, কম বর্জ্য"
BULLETS = [
    "মানসম্পন্ন ম্যাটেরিয়াল ও বিল্ড",
    "হাতে তৈরি ড্রেসে টেকসই ফেব্রিক ও সেলাই",
    "কম রিপ্লেসমেন্ট, কম ই-বর্জ্য",
    "হাতে পেয়ে দেখে তারপর পেমেন্ট",
]


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
        "title": TITLE,
        "body": "Seed body",
        "image": {"src": PHOTO, "alt": "হাতে তৈরি গর্জিয়াস ড্রেস — টেকসই ফেব্রিক ও সেলাই"},
        "bullets": [{"text": text, "is_active": True} for text in BULLETS],
    }
    body.update(overrides)
    return body


async def test_public_sustainability_durability_seeds_the_block(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/sustainability/durability")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == TITLE
    assert body["image"]["src"] == PHOTO
    assert [bullet["text"] for bullet in body["bullets"]] == BULLETS
    assert "is_active" not in body["bullets"][0]


async def test_sustainability_durability_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/sustainability/durability")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "sustain-durability-viewer@implesia.com",
            "full_name": "Sustain Durability Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "sustain-durability-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.put(
        "/api/v1/admin/pages/sustainability/durability",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        files=_parts(_seed_body(title="Nope")),
    )
    assert denied.status_code == 403


async def test_editor_can_hide_upload_and_restore_durability(
    client: AsyncClient, auth_headers: dict[str, str], tmp_path, monkeypatch
) -> None:
    from app.core.config import settings
    from app.services.sustainability import durability_service

    monkeypatch.setattr(settings, "media_root", tmp_path)
    monkeypatch.setattr(durability_service, "MAX_BULLETS", 3)
    blocked = await client.put(
        "/api/v1/admin/pages/sustainability/durability",
        headers=auth_headers,
        files=_parts(
            _seed_body(bullets=[*[{"text": text} for text in BULLETS[:3]], {"text": "Extra"}])
        ),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can add up to 12 points"
    monkeypatch.setattr(durability_service, "MAX_BULLETS", 12)

    blank = await client.put(
        "/api/v1/admin/pages/sustainability/durability",
        headers=auth_headers,
        files=_parts(_seed_body(title="   ")),
    )
    assert blank.status_code == 422
    assert blank.json()["error"]["message"] == "Title is required."

    missing_photo = await client.put(
        "/api/v1/admin/pages/sustainability/durability",
        headers=auth_headers,
        files=_parts(_seed_body(image={"src": "", "alt": ""})),
    )
    assert missing_photo.status_code == 422
    assert missing_photo.json()["error"]["message"] == "Cover photo is required."

    staged = await client.put(
        "/api/v1/admin/pages/sustainability/durability",
        headers=auth_headers,
        files=_parts(_seed_body(image={"src": "blob:durability", "alt": "Right"})),
    )
    assert staged.status_code == 422
    assert staged.json()["error"]["message"] == "Send the image file with the durability"

    empty_point = await client.put(
        "/api/v1/admin/pages/sustainability/durability",
        headers=auth_headers,
        files=_parts(_seed_body(bullets=[{"text": "   "}])),
    )
    assert empty_point.status_code == 422
    assert empty_point.json()["error"]["message"] == "Write each point, or remove the empty one."

    hidden = await client.put(
        "/api/v1/admin/pages/sustainability/durability",
        headers=auth_headers,
        files=_parts(
            _seed_body(
                bullets=[
                    {"text": BULLETS[0], "is_active": True},
                    {"text": BULLETS[1], "is_active": False},
                    {"text": BULLETS[2], "is_active": True},
                    {"text": BULLETS[3], "is_active": True},
                ]
            )
        ),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["bullets"][1]["is_active"] is False
    public = await client.get("/api/v1/pages/sustainability/durability")
    assert [bullet["text"] for bullet in public.json()["bullets"]] == [
        BULLETS[0],
        BULLETS[2],
        BULLETS[3],
    ]

    uploaded = await client.put(
        "/api/v1/admin/pages/sustainability/durability",
        headers=auth_headers,
        files=_parts(
            _seed_body(image={"src": "", "alt": "Upload"}),
            ("durability.jpg", JPEG, "image/jpeg"),
        ),
    )
    assert uploaded.status_code == 200, uploaded.text
    stored = uploaded.json()["image"]["src"]
    assert stored.startswith("/media/sustainability/")
    assert (tmp_path / stored.removeprefix("/media/")).is_file()

    restored = await client.put(
        "/api/v1/admin/pages/sustainability/durability",
        headers=auth_headers,
        files=_parts(_seed_body()),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["image"]["src"] == PHOTO
    assert [bullet["text"] for bullet in restored.json()["bullets"]] == BULLETS
    assert not (tmp_path / stored.removeprefix("/media/")).exists()
