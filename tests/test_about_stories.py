import json

from httpx import AsyncClient

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
LAMP = "/images/products/lamp/lamp-2.jpg"
FROCK = "/images/products/baby-products/baby-frock-with-baby.jpeg"


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
        "title": "Bruno story check",
        "paragraphs": [{"text": "A hidden story."}],
        "cta_label": "",
        "cta_href": "",
        "is_active": False,
        "images": [],
    }
    body.update(overrides)
    return body


async def test_public_about_stories_seed_the_block(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pages/about/stories")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    story = items[0]
    assert story["kicker"] == "আমাদের যাত্রা"
    assert story["title"] == "কেন ইমপ্লেসিয়া মার্ট শুরু হলো"
    assert story["cta_label"] == "সব প্রোডাক্ট"
    assert story["cta_href"] == "/products"
    assert len(story["paragraphs"]) == 3
    assert story["paragraphs"][0]["text"].startswith("অনলাইনে অর্ডার করা")
    assert story["paragraphs"][2]["text"].endswith("আসল লক্ষ্য।")
    assert [image["src"] for image in story["images"]] == [LAMP, FROCK]
    assert "is_active" not in story


async def test_about_stories_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/pages/about/stories")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "about-story-viewer@implesia.com",
            "full_name": "About Story Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "about-story-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.post(
        "/api/v1/admin/pages/about/stories",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        files=_parts(_hidden()),
    )
    assert denied.status_code == 403


async def test_editor_can_hide_reorder_upload_and_remove_a_story(
    client: AsyncClient, auth_headers: dict[str, str], tmp_path, monkeypatch
) -> None:
    from app.core.config import settings
    from app.services.about import story_service

    monkeypatch.setattr(settings, "media_root", tmp_path)
    monkeypatch.setattr(story_service, "MAX_STORIES", 1)
    blocked = await client.post(
        "/api/v1/admin/pages/about/stories",
        headers=auth_headers,
        files=_parts(_hidden()),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["message"] == "You can show up to 12 stories"
    monkeypatch.setattr(story_service, "MAX_STORIES", 12)

    empty = await client.post(
        "/api/v1/admin/pages/about/stories",
        headers=auth_headers,
        files=_parts(_hidden(title="   ", paragraphs=[])),
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["message"] == "Add a title or some story text."

    button = await client.post(
        "/api/v1/admin/pages/about/stories",
        headers=auth_headers,
        files=_parts(_hidden(cta_label="Shop", cta_href="")),
    )
    assert button.status_code == 422
    assert (
        button.json()["error"]["message"]
        == "Add a link for the button, or clear the button label."
    )

    created = await client.post(
        "/api/v1/admin/pages/about/stories",
        headers=auth_headers,
        files=_parts(
            _hidden(
                title="  Checked  ",
                images=[{"alt": "  Uploaded  ", "src": ""}],
            ),
            ("story.jpg", JPEG, "image/jpeg"),
        ),
    )
    assert created.status_code == 201, created.text
    story = created.json()
    assert story["title"] == "Checked"
    assert story["is_active"] is False
    assert story["images"][0]["alt"] == "Uploaded"
    assert story["images"][0]["src"].startswith("/media/about/")
    stored = tmp_path / "about" / story["images"][0]["src"].removeprefix("/media/about/")
    assert stored.is_file()

    public = await client.get("/api/v1/pages/about/stories")
    assert len(public.json()["items"]) == 1
    assert public.json()["items"][0]["title"] == "কেন ইমপ্লেসিয়া মার্ট শুরু হলো"

    listed = await client.get("/api/v1/admin/pages/about/stories", headers=auth_headers)
    ids = [item["id"] for item in listed.json()]
    moved = await client.put(
        "/api/v1/admin/pages/about/stories/order",
        headers=auth_headers,
        json={"ids": [story["id"], *ids[:-1]]},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()[0]["id"] == story["id"]

    incomplete = await client.put(
        "/api/v1/admin/pages/about/stories/order",
        headers=auth_headers,
        json={"ids": [story["id"]]},
    )
    assert incomplete.status_code == 422

    removed = await client.delete(
        f"/api/v1/admin/pages/about/stories/{story['id']}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    assert removed.json()["message"] == "Story removed"
    assert not stored.exists()

    again = await client.get("/api/v1/pages/about/stories")
    assert [item["title"] for item in again.json()["items"]] == ["কেন ইমপ্লেসিয়া মার্ট শুরু হলো"]
