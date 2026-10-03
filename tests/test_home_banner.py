from httpx import AsyncClient


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
        json={"is_published": False},
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
        json={
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
        },
    )
    assert created.status_code == 201, created.text
    slide_id = created.json()["id"]
    assert created.json()["price_label"] == "৳500"
    assert created.json()["discount_label"] == "50% ছাড়"

    duplicate = await client.post(
        "/api/v1/admin/home/banner/slides",
        headers=auth_headers,
        json=created.json()
        | {
            "slug": "bruno-style-slide",
            "primary_cta_label": "অর্ডার",
            "primary_cta_href": "/products/bruno-style-slide",
            "secondary_cta_label": "সব",
            "secondary_cta_href": "/products",
        },
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
