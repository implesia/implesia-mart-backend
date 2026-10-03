import json

from httpx import AsyncClient

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
LEFT = "/images/products/lamp/lamp-1.jpg"
RIGHT = "/images/products/baby-products/female-gorgious-ground-dress.jpeg"


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
        "eyebrow": "সাসটেইনেবিলিটি",
        "title": "দায়িত্বশীল শপিং, দীর্ঘস্থায়ী প্রোডাক্ট",
        "subtitle": (
            "ভালো প্রোডাক্ট মানেই কম রিপ্লেসমেন্ট, কম বর্জ্য। গ্যাজেট যাচাই করে আর গর্জিয়াস ড্রেস "
            "হাতে তৈরি করে — দায়িত্বশীল প্যাকেজিংয়ে পাঠাই।"
        ),
        "primary_label": "সব প্রোডাক্ট",
        "primary_href": "/products",
        "secondary_label": "আমাদের সম্পর্কে",
        "secondary_href": "/about-us",
        "images": [
            {"alt": "সানসেট ল্যাম্প — কোয়ালিটি চেক করা গ্যাজেট", "src": LEFT},
            {"alt": "হাতে তৈরি গর্জিয়াস উইমেন্স গাউন", "src": RIGHT},
        ],
    }
    body.update(overrides)
    return body


async def test_public_sustainability_hero_seeds_the_banner(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/sustainability/hero")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eyebrow"] == "সাসটেইনেবিলিটি"
    assert body["title"] == "দায়িত্বশীল শপিং, দীর্ঘস্থায়ী প্রোডাক্ট"
    assert body["primary_label"] == "সব প্রোডাক্ট"
    assert body["secondary_href"] == "/about-us"
    assert [image["src"] for image in body["images"]] == [LEFT, RIGHT]
    assert "sort_order" not in body["images"][0]


async def test_sustainability_hero_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/sustainability/hero")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "sustain-hero-viewer@implesia.com",
            "full_name": "Sustain Hero Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "sustain-hero-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.put(
        "/api/v1/admin/pages/sustainability/hero",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        files=_parts(_seed_body(title="Nope")),
    )
    assert denied.status_code == 403


async def test_editor_saves_copy_and_a_photo_together(
    client: AsyncClient, auth_headers: dict[str, str], tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "media_root", tmp_path)
    seeded = await client.get("/api/v1/admin/pages/sustainability/hero", headers=auth_headers)
    assert seeded.status_code == 200, seeded.text
    original_ids = [image["id"] for image in seeded.json()["images"]]

    staged = await client.put(
        "/api/v1/admin/pages/sustainability/hero",
        headers=auth_headers,
        files=_parts(
            _seed_body(
                images=[{"alt": "Left", "src": "blob:hero"}, {"alt": "Right", "src": RIGHT}]
            )
        ),
    )
    assert staged.status_code == 422
    assert staged.json()["error"]["message"] == "Send the image file with the hero"

    blank = await client.put(
        "/api/v1/admin/pages/sustainability/hero",
        headers=auth_headers,
        files=_parts(_seed_body(title="   ")),
    )
    assert blank.status_code == 422

    empty_photo = await client.put(
        "/api/v1/admin/pages/sustainability/hero",
        headers=auth_headers,
        files=_parts(
            _seed_body(images=[{"alt": "Left", "src": ""}, {"alt": "Right", "src": RIGHT}])
        ),
    )
    assert empty_photo.status_code == 422
    assert empty_photo.json()["error"]["message"] == "Both banner photos are required."

    saved = await client.put(
        "/api/v1/admin/pages/sustainability/hero",
        headers=auth_headers,
        files=_parts(
            _seed_body(
                title="  Checked title  ",
                images=[{"alt": "  Uploaded  ", "src": ""}, {"alt": "Right", "src": RIGHT}],
            ),
            ("hero.jpg", JPEG, "image/jpeg"),
        ),
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["title"] == "Checked title"
    assert body["images"][0]["alt"] == "Uploaded"
    assert body["images"][0]["src"].startswith("/media/sustainability/")
    assert body["images"][0]["id"] == original_ids[0]
    assert body["images"][1]["src"] == RIGHT
    stored = tmp_path / "sustainability" / body["images"][0]["src"].removeprefix(
        "/media/sustainability/"
    )
    assert stored.is_file()

    public = await client.get("/api/v1/pages/sustainability/hero")
    assert public.json()["title"] == "Checked title"
    assert public.json()["images"][0]["src"] == body["images"][0]["src"]

    restored = await client.put(
        "/api/v1/admin/pages/sustainability/hero",
        headers=auth_headers,
        files=_parts(_seed_body()),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["title"] == "দায়িত্বশীল শপিং, দীর্ঘস্থায়ী প্রোডাক্ট"
    assert [image["src"] for image in restored.json()["images"]] == [LEFT, RIGHT]
    assert not stored.exists()
