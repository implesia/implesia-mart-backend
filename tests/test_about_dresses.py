import json

from httpx import AsyncClient

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
GALLERY = [
    "/images/products/baby-products/baby-frock-with-baby.jpeg",
    "/images/products/baby-products/female-gorgious-ground-dress.jpeg",
    "/images/products/baby-products/baby-ground-frog-more.jpeg",
    "/images/products/baby-products/baby-ground-frog-3.jpeg",
    "/images/products/baby-products/3-quater-ground-frog2.jpeg",
    "/images/products/baby-products/baby-jama-pant.jpeg",
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


def _hidden(**overrides: object) -> dict:
    body = {
        "kicker": "",
        "title": "Bruno dress check",
        "subtitle": "",
        "features": [],
        "primary_label": "",
        "primary_href": "",
        "secondary_label": "",
        "secondary_href": "",
        "is_active": False,
        "images": [],
    }
    body.update(overrides)
    return body


async def test_public_about_dresses_seed_the_block(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/about/dresses")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    dress = items[0]
    assert dress["kicker"] == "নতুন সংযোজন"
    assert dress["title"] == "শুধু গ্যাজেট নয়, আমরা তৈরি করি গর্জিয়াস ড্রেসও"
    assert dress["primary_label"] == "কাস্টম অর্ডার"
    assert dress["primary_href"].startswith("https://wa.me/8801516527932?text=")
    assert dress["secondary_label"] == "গর্জিয়াস ড্রেস"
    assert dress["secondary_href"] == "/products?category=fashion"
    assert [item["title"] for item in dress["features"]] == [
        "কাস্টম ডিজাইন",
        "১০০% হাতে তৈরি",
        "বাচ্চা ও নারীদের জন্য",
        "প্রিমিয়াম কোয়ালিটি",
    ]
    assert dress["features"][0]["icon"] == "design_services"
    assert [image["src"] for image in dress["images"]] == GALLERY
    assert "is_active" not in dress


async def test_about_dresses_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/about/dresses")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "about-dress-viewer@implesia.com",
            "full_name": "About Dress Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "about-dress-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/pages/about/dresses",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        files=_parts(_hidden()),
    )
    assert denied.status_code == 403


async def test_editor_can_hide_reorder_upload_and_remove_a_dress(
    client: AsyncClient, auth_headers: dict[str, str], tmp_path, monkeypatch
) -> None:
    from app.core.config import settings
    from app.services.about import dress_service

    monkeypatch.setattr(settings, "media_root", tmp_path)
    monkeypatch.setattr(dress_service, "MAX_DRESSES", 1)
    blocked = await client.post(
        "/api/v1/admin/pages/about/dresses",
        headers=auth_headers,
        files=_parts(_hidden()),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can show up to 12 custom dresses"
    monkeypatch.setattr(dress_service, "MAX_DRESSES", 12)

    empty = await client.post(
        "/api/v1/admin/pages/about/dresses",
        headers=auth_headers,
        files=_parts(_hidden(title="   ", features=[])),
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["message"] == "Add a title or some text."

    button = await client.post(
        "/api/v1/admin/pages/about/dresses",
        headers=auth_headers,
        files=_parts(_hidden(primary_label="Order", primary_href="")),
    )
    assert button.status_code == 422
    assert button.json()["error"]["message"] == (
        "Add a link for each button that has a label, or clear the label."
    )

    created = await client.post(
        "/api/v1/admin/pages/about/dresses",
        headers=auth_headers,
        files=_parts(
            _hidden(title="  Checked  ", images=[{"alt": "  Uploaded  ", "src": ""}]),
            ("dress.jpg", JPEG, "image/jpeg"),
        ),
    )
    assert created.status_code == 201, created.text
    dress = created.json()
    assert dress["title"] == "Checked"
    assert dress["is_active"] is False
    assert dress["images"][0]["alt"] == "Uploaded"
    assert dress["images"][0]["src"].startswith("/media/about/")
    stored = tmp_path / "about" / dress["images"][0]["src"].removeprefix("/media/about/")
    assert stored.is_file()

    public = await client.get("/api/v1/pages/about/dresses")
    assert len(public.json()["items"]) == 1
    assert public.json()["items"][0]["title"] == "শুধু গ্যাজেট নয়, আমরা তৈরি করি গর্জিয়াস ড্রেসও"

    listed = await client.get("/api/v1/admin/pages/about/dresses", headers=auth_headers)
    ids = [item["id"] for item in listed.json()]
    moved = await client.put(
        "/api/v1/admin/pages/about/dresses/order",
        headers=auth_headers,
        json={"ids": [dress["id"], *ids[:-1]]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()[0]["id"] == dress["id"]

    incomplete = await client.put(
        "/api/v1/admin/pages/about/dresses/order",
        headers=auth_headers,
        json={"ids": [dress["id"]]},
    )
    assert incomplete.status_code == 422

    removed = await client.delete(
        f"/api/v1/admin/pages/about/dresses/{dress['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Custom dress removed"
    assert not stored.exists()

    again = await client.get("/api/v1/pages/about/dresses")
    titles = [item["title"] for item in again.json()["items"]]
    assert titles == ["শুধু গ্যাজেট নয়, আমরা তৈরি করি গর্জিয়াস ড্রেসও"]
