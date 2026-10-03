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


async def test_public_banner_matches_the_live_hero(client: AsyncClient) -> None:
    response = await client.get("/api/v1/home/banner")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["brand_name"] == "Implesia Mart"
    assert body["aria_label"] == "ফিচার্ড প্রোডাক্ট"
    assert body["trust_line"] == "সারাদেশে ক্যাশ অন ডেলিভারি · ৩ দিনের ইজি রিটার্ন"
    assert body["previous_label"] == "আগের স্লাইড"
    assert body["next_label"] == "পরের স্লাইড"
    assert body["slide_label"] == "স্লাইড"
    assert body["autoplay_delay_ms"] == 6500
    assert body["transition_speed_ms"] == 750
    assert body["pause_on_hover"] is True
    assert body["loop"] is True
    assert body["keyboard_enabled"] is True
    assert body["disable_on_interaction"] is False
    assert body["cross_fade"] is True
    assert body["effect"] == "fade"

    slides = body["slides"]
    assert [slide["slug"] for slide in slides] == [
        "sunset-rainbow-projection-lamp",
        "ai-face-tracking-phone-holder",
        "custom-gorgeous-womens-gown",
        "custom-baby-party-frock",
        "slim-power-bank-10000mah",
    ]
    lamp = slides[0]
    assert lamp["price_label"] == "৳999"
    assert lamp["compare_at_label"] == "৳1,499"
    assert lamp["discount_label"] == "33% ছাড়"
    assert lamp["primary_cta"] == {
        "label": "এখনই অর্ডার",
        "href": "/products/sunset-rainbow-projection-lamp",
    }
    assert lamp["accent"] == "gold"
    assert lamp["image_priority"] is True
    assert slides[1]["image_priority"] is False
    assert lamp["image_src"] == "/images/products/lamp/lamp-5.jpg"
    gown = slides[2]
    assert gown["price_label"] == "শুরু ৳15,000"
    assert gown["compare_at_label"] is None
    assert gown["discount_label"] is None
    power = slides[4]
    assert power["price_label"] == "৳1,299"
    assert power["discount_label"] == "28% ছাড়"


async def test_unpublished_slides_stay_off_the_public_banner(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    listed = await client.get("/api/v1/admin/home/banner/slides", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    lamp_id = listed.json()["items"][0]["id"]

    hidden = await client.patch(
        f"/api/v1/admin/home/banner/slides/{lamp_id}",
        headers=auth_headers,
        files=_parts({"is_published": False}),
    )
    assert hidden.status_code == 200, hidden.text

    public = await client.get("/api/v1/home/banner")
    slugs = [slide["slug"] for slide in public.json()["slides"]]
    assert "sunset-rainbow-projection-lamp" not in slugs
    assert len(slugs) == 4


async def test_banner_admin_requires_an_editor(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    anonymous = await client.get("/api/v1/admin/home/banner")
    assert anonymous.status_code == 401

    created = await client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "banner-viewer@implesia.com",
            "full_name": "Banner Viewer",
            "password": "viewer-passphrase",
            "role": "viewer",
            "is_active": True,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "banner-viewer@implesia.com", "password": "viewer-passphrase"},
    )
    denied = await client.patch(
        "/api/v1/admin/home/banner",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        json={"brand_name": "Nope"},
    )
    assert denied.status_code == 403


async def test_editor_can_replace_banner_chrome_and_manage_a_slide(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    updated = await client.patch(
        "/api/v1/admin/home/banner",
        headers=auth_headers,
        json={"trust_line": "টেস্ট ট্রাস্ট লাইন", "autoplay_delay_ms": 4000},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["trust_line"] == "টেস্ট ট্রাস্ট লাইন"
    assert updated.json()["autoplay_delay_ms"] == 4000

    public = await client.get("/api/v1/home/banner")
    assert public.json()["trust_line"] == "টেস্ট ট্রাস্ট লাইন"
    assert public.json()["autoplay_delay_ms"] == 4000

    created = await client.post(
        "/api/v1/admin/home/banner/slides",
        headers=auth_headers,
        files=_parts(
            {
                "slug": "bruno-style-slide",
                "eyebrow": "টেস্ট",
                "title": "নতুন স্লাইড",
                "description": "অ্যাডমিন থেকে যোগ করা স্লাইড।",
                "price": 500,
                "compare_at_price": 1000,
                "primary_cta_label": "অর্ডার",
                "primary_cta_href": "/products/bruno-style-slide",
                "secondary_cta_label": "সব",
                "secondary_cta_href": "/products",
                "image_src": "/images/products/lamp/lamp-5.jpg",
                "image_alt": "টেস্ট",
                "accent": "teal",
                "sort_order": 9,
            }
        ),
    )
    assert created.status_code == 201, created.text
    slide_id = created.json()["id"]
    assert created.json()["price_label"] == "৳500"
    assert created.json()["discount_label"] == "50% ছাড়"

    duplicate = await client.post(
        "/api/v1/admin/home/banner/slides",
        headers=auth_headers,
        files=_parts(
            {
                "slug": "bruno-style-slide",
                "title": "নতুন স্লাইড",
                "image_src": "/images/products/lamp/lamp-5.jpg",
            }
        ),
    )
    assert duplicate.status_code == 409

    removed = await client.delete(
        f"/api/v1/admin/home/banner/slides/{slide_id}",
        headers=auth_headers,
    )
    assert removed.status_code == 200
    missing = await client.get(
        f"/api/v1/admin/home/banner/slides/{slide_id}",
        headers=auth_headers,
    )
    assert missing.status_code == 404


async def test_hero_form_can_create_reorder_and_hide_a_draft(
    client: AsyncClient, auth_headers: dict[str, str], tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "media_root", tmp_path)
    created = await client.post(
        "/api/v1/admin/home/banner/slides",
        headers=auth_headers,
        files=_parts(
            {
                "title": "Desk lamp",
                "eyebrow": "New",
                "description": "A short line.",
                "price_label": "শুরু ৳1,500",
                "primary_cta_label": "Order now",
                "primary_cta_href": "/products",
                "image_alt": "Desk lamp",
                "accent": "teal",
                "is_published": True,
            },
            ("desk-lamp.jpg", JPEG, "image/jpeg"),
        ),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["slug"] == "desk-lamp"
    assert body["price_label"] == "শুরু ৳1,500"
    assert body["price"] == 1500
    assert body["image_src"].startswith("/media/banners/")
    stored = tmp_path / "banners" / body["image_src"].removeprefix("/media/banners/")
    assert stored.is_file()
    slide_id = body["id"]

    listed = await client.get(
        "/api/v1/admin/home/banner/slides?page_size=100", headers=auth_headers
    )
    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json()["items"]]
    assert ids[-1] == slide_id

    moved = await client.post(
        f"/api/v1/admin/home/banner/slides/{slide_id}/move",
        headers=auth_headers,
        json={"direction": "earlier"},
    )
    assert moved.status_code == 200, moved.text
    again = await client.get(
        "/api/v1/admin/home/banner/slides?page_size=100", headers=auth_headers
    )
    assert [item["id"] for item in again.json()["items"]][-2] == slide_id

    draft = await client.post(
        "/api/v1/admin/home/banner/slides",
        headers=auth_headers,
        files=_parts({"title": "", "price_label": "", "image_src": "", "is_published": True}),
    )
    assert draft.status_code == 201, draft.text
    public = await client.get("/api/v1/home/banner")
    public_ids = {slide["id"] for slide in public.json()["slides"]}
    assert slide_id in public_ids
    assert draft.json()["id"] not in public_ids
    assert draft.json()["price_label"] == ""

    await client.delete(f"/api/v1/admin/home/banner/slides/{slide_id}", headers=auth_headers)
    await client.delete(
        f"/api/v1/admin/home/banner/slides/{draft.json()['id']}", headers=auth_headers
    )
    assert not stored.is_file()

    staged = await client.post(
        "/api/v1/admin/home/banner/slides",
        headers=auth_headers,
        files=_parts({"title": "Local only", "image_src": "/uploads/desk-lamp.jpg"}),
    )
    assert staged.status_code == 422

    rejected = await client.post(
        "/api/v1/admin/home/banner/slides",
        headers=auth_headers,
        files=_parts(
            {"title": "Svg"},
            ("icon.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
        ),
    )
    assert rejected.status_code == 422
