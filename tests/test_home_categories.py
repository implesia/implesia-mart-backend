import json

from httpx import AsyncClient

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)


def _parts(
    body: dict, image: tuple[str, bytes, str] | None = None
) -> list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]]:
    parts: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
        ("payload", (None, json.dumps(body)))
    ]
    if image is not None:
        parts.append(("image", image))
    return parts


async def test_public_categories_seed_the_home_grid(client: AsyncClient) -> None:
    response = await client.get("/api/v1/home/categories")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["heading"] == "ক্যাটাগরি"
    assert [tile["label"] for tile in body["tiles"]] == ["ট্রেন্ডিং গ্যাজেট", "গর্জিয়াস ড্রেস"]
    assert body["tiles"][0]["href"] == "/products?category=gadgets"
    assert body["tiles"][0]["image_src"] == "/images/products/lamp/lamp-5.jpg"
    assert "is_active" not in body["tiles"][0]


async def test_category_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/home/categories")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "category-viewer@implesia.com",
            "full_name": "Category Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "category-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/home/categories/tiles",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        files=_parts({"label": "Nope"}),
    )
    assert denied.status_code == 403


async def test_editor_can_create_reorder_hide_and_remove_a_category(
    client: AsyncClient, auth_headers: dict[str, str], tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "media_root", tmp_path)
    heading = await client.patch(
        "/api/v1/admin/home/categories",
        headers=auth_headers,
        json={"heading": "শপ"},
    )
    assert heading.status_code == 200, heading.text
    assert heading.json()["heading"] == "শপ"

    created = await client.post(
        "/api/v1/admin/home/categories/tiles",
        headers=auth_headers,
        files=_parts(
            {"label": "  Checked  ", "href": "", "is_active": False},
            ("tile.jpg", JPEG, "image/jpeg"),
        ),
    )
    assert created.status_code == 201, created.text
    tile = created.json()
    assert tile["label"] == "Checked"
    assert tile["href"] == "/products"
    assert tile["is_active"] is False
    assert tile["image_src"].startswith("/media/categories/")
    stored = tmp_path / "categories" / tile["image_src"].removeprefix("/media/categories/")
    assert stored.is_file()

    public = await client.get("/api/v1/home/categories")
    labels = [item["label"] for item in public.json()["tiles"]]
    assert "Checked" not in labels
    assert public.json()["heading"] == "শপ"

    listed = await client.get("/api/v1/admin/home/categories", headers=auth_headers)
    ids = [item["id"] for item in listed.json()["tiles"]]
    moved = await client.put(
        "/api/v1/admin/home/categories/tiles/order",
        headers=auth_headers,
        json={"ids": [tile["id"], *ids[:-1]]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["tiles"][0]["id"] == tile["id"]

    incomplete = await client.put(
        "/api/v1/admin/home/categories/tiles/order",
        headers=auth_headers,
        json={"ids": [tile["id"]]},
    )
    assert incomplete.status_code == 422

    blank = await client.post(
        "/api/v1/admin/home/categories/tiles",
        headers=auth_headers,
        files=_parts({"label": "   "}),
    )
    assert blank.status_code == 422

    staged = await client.post(
        "/api/v1/admin/home/categories/tiles",
        headers=auth_headers,
        files=_parts({"label": "Local", "image_src": "/uploads/tile.jpg"}),
    )
    assert staged.status_code == 422

    removed = await client.delete(
        f"/api/v1/admin/home/categories/tiles/{tile['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Category deleted"
    assert not stored.is_file()

    restored = await client.patch(
        "/api/v1/admin/home/categories",
        headers=auth_headers,
        json={"heading": "ক্যাটাগরি"},
    )
    assert restored.status_code == 200
    again = await client.get("/api/v1/home/categories")
    assert [item["label"] for item in again.json()["tiles"]] == [
        "ট্রেন্ডিং গ্যাজেট",
        "গর্জিয়াস ড্রেস",
    ]
