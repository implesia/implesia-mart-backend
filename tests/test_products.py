import json
import re

from httpx import AsyncClient

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)


def _product(**overrides: object) -> dict:
    body: dict = {
        "title": "Gorgeous Womens Gown",
        "subtitle": "Hand embroidered custom gown",
        "category": "fashion",
        "price": 15000,
        "compare_at_price": None,
        "quantity": None,
        "status": "available",
        "badge": "New",
        "image_src": "/images/products/gown.jpg",
        "featured": True,
        "published": True,
        "content": {
            "tagline": "হাতে তৈরি",
            "description": "কাস্টম এমব্রয়ডারি গাউন।",
            "unit_label": "শুরু",
            "image_alt": "গর্জিয়াস গাউন",
            "highlights": ["হাতে তৈরি"],
            "specs": [{"label": "কাপড়", "value": "কটন", "group": "fabric"}],
            "faqs": [{"question": "কত দিন?", "answer": "৩-৭ কর্মদিবস।"}],
        },
    }
    body.update(overrides)
    return body


def _parts(
    body: dict,
    images: list[tuple[str, bytes, str]] | None = None,
    alts: list[str] | None = None,
    quality: tuple[str, bytes, str] | None = None,
    quality_alt: str = "",
) -> list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]]:
    parts: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
        ("payload", (None, json.dumps(body)))
    ]
    if alts is not None:
        parts.append(("image_alts", (None, json.dumps(alts))))
    if quality_alt:
        parts.append(("quality_image_alt", (None, quality_alt)))
    for image in images or []:
        parts.append(("images", image))
    if quality is not None:
        parts.append(("quality_image", quality))
    return parts


async def _create(client: AsyncClient, headers: dict[str, str], **overrides: object) -> dict:
    response = await client.post(
        "/api/v1/admin/products",
        headers=headers,
        files=_parts(_product(**overrides)),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_catalog_follows_the_product_pages(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(
        client,
        auth_headers,
        slug="custom-gorgeous-womens-gown",
        quantity=4,
    )
    assert created["slug"] == "custom-gorgeous-womens-gown"
    assert created["quantity"] == 4
    assert created["content"]["unit_label"] == "শুরু"
    assert created["content"]["highlights"] == ["হাতে তৈরি"]
    assert "password" not in created

    listed = await client.get(
        "/api/v1/admin/products",
        headers=auth_headers,
        params={"category": "fashion", "q": "gown"},
    )
    assert listed.status_code == 200, listed.text
    assert listed.headers["cache-control"] == "no-store"
    body = listed.json()
    assert body["total"] == 1
    assert body["pages"] == 1
    assert body["metrics"]["total"] == 1
    assert body["metrics"]["live"] == 1
    card = body["items"][0]
    assert card["slug"] == "custom-gorgeous-womens-gown"
    assert "content" not in card
    assert "highlights" not in card

    public = await client.get(f"/api/v1/products/{created['id']}")
    assert public.status_code == 200, public.text
    detail = public.json()
    assert detail["id"] == created["id"]
    assert detail["title"] == "Gorgeous Womens Gown"
    assert detail["price"] == 15000
    assert detail["unit_label"] == "শুরু"
    assert detail["highlights"] == ["হাতে তৈরি"]
    assert detail["specs"][0]["group"] == "fabric"
    assert detail["faqs"][0]["question"] == "কত দিন?"
    assert detail["gallery"][0]["src"] == "/images/products/gown.jpg"
    assert "quantity" not in detail
    assert "published" not in detail
    assert "content" not in detail

    catalog = await client.get(
        "/api/v1/products",
        params={"category": "fashion", "view": "featured", "page_size": 8},
    )
    assert catalog.status_code == 200, catalog.text
    page = catalog.json()
    assert page["total"] == 1
    assert page["pages"] == 1
    assert page["items"][0]["slug"] == "custom-gorgeous-womens-gown"
    assert "quantity" not in page["items"][0]
    assert page["category_counts"]["fashion"] == 1


async def test_a_new_product_stays_off_the_public_catalog(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    body = _product(title="Night upload check", slug="night-upload-check")
    del body["published"]
    response = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(body),
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["published"] is False

    public = await client.get(f"/api/v1/products/{created['id']}")
    assert public.status_code == 404

    catalog = await client.get("/api/v1/products")
    assert all(item["title"] != "Night upload check" for item in catalog.json()["items"])


async def test_hidden_products_are_not_confirmed(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create(client, auth_headers, title="Hidden Lamp", published=False)
    public = await client.get(f"/api/v1/products/{created['id']}")
    assert public.status_code == 404
    assert public.json()["error"]["code"] == "not_found"

    missing = await client.get("/api/v1/products/00000000-0000-4000-8000-000000000001")
    assert missing.status_code == 404
    assert missing.json() == public.json()

    catalog = await client.get("/api/v1/products")
    assert all(item["id"] != created["id"] for item in catalog.json()["items"])

    admin = await client.get(
        f"/api/v1/admin/products/{created['id']}",
        headers=auth_headers,
    )
    assert admin.status_code == 200
    assert admin.json()["published"] is False


async def test_related_products_stay_in_category_and_published(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    gown = await _create(client, auth_headers, title="Gown A", slug="gown-a")
    await _create(client, auth_headers, title="Gown B", slug="gown-b", featured=False)
    await _create(client, auth_headers, title="Hidden Gown", slug="gown-hidden", published=False)
    await _create(
        client,
        auth_headers,
        title="Sunset Lamp",
        slug="sunset-lamp",
        category="gadgets",
        price=999,
        featured=False,
    )

    detail = await client.get(f"/api/v1/products/{gown['id']}")
    related = [item["slug"] for item in detail.json()["related"]]
    assert related == ["gown-b"]


async def test_admin_filters_match_the_products_table(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(
        client,
        auth_headers,
        title="Alpha Lamp",
        category="gadgets",
        price=400,
        featured=False,
    )
    await _create(
        client,
        auth_headers,
        title="Beta Cable",
        category="gadgets",
        price=900,
        status="sold-out",
        quantity=0,
        featured=False,
        badge=None,
    )
    await _create(
        client,
        auth_headers,
        title="Hidden Dress",
        category="fashion",
        price=2000,
        published=False,
        featured=False,
        badge=None,
    )

    sold = await client.get(
        "/api/v1/admin/products",
        headers=auth_headers,
        params={"status": "sold-out", "sort": "stock-asc"},
    )
    assert sold.status_code == 200, sold.text
    assert [item["title"] for item in sold.json()["items"]] == ["Beta Cable"]
    assert sold.json()["metrics"]["sold_out"] == 1
    assert sold.json()["metrics"]["total"] == 3
    assert sold.json()["category_counts"] == {"all": 1, "gadgets": 1, "fashion": 0}

    ranked = await client.get(
        "/api/v1/admin/products",
        headers=auth_headers,
        params={"category": "gadgets", "sort": "stock-asc"},
    )
    assert [item["title"] for item in ranked.json()["items"]] == ["Beta Cable", "Alpha Lamp"]

    names = await client.get(
        "/api/v1/admin/products",
        headers=auth_headers,
        params={"sort": "name-asc"},
    )
    assert [item["title"] for item in names.json()["items"]] == [
        "Alpha Lamp",
        "Beta Cable",
        "Hidden Dress",
    ]

    search = await client.get(
        "/api/v1/admin/products",
        headers=auth_headers,
        params={"q": "gorgeous dresses"},
    )
    assert [item["title"] for item in search.json()["items"]] == ["Hidden Dress"]
    assert search.json()["total"] == 1
    assert search.json()["metrics"]["total"] == 3

    wildcard = await client.get(
        "/api/v1/admin/products",
        headers=auth_headers,
        params={"q": "%"},
    )
    assert wildcard.json()["total"] == 0

    priced = await client.get(
        "/api/v1/products",
        params={"min_price": 500, "max_price": 1000, "status": "sold-out"},
    )
    assert [item["title"] for item in priced.json()["items"]] == ["Beta Cable"]
    assert priced.json()["availability_counts"]["sold_out"] == 1
    assert priced.json()["availability_counts"]["available"] == 0


async def test_writes_require_an_editor(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    anonymous = await client.get("/api/v1/admin/products")
    assert anonymous.status_code == 401

    for role, email in (("viewer", "viewer@implesia.com"), ("editor", "editor@implesia.com")):
        created = await client.post(
            "/api/v1/users",
            headers=auth_headers,
            json={
                "email": email,
                "full_name": role,
                "password": f"{role}-passphrase",
                "role": role,
                "is_active": True,
            },
        )
        assert created.status_code == 201, created.text
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": f"{role}-passphrase"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        response = await client.post(
            "/api/v1/admin/products", headers=headers, files=_parts(_product())
        )
        if role == "viewer":
            assert response.status_code == 403
        else:
            assert response.status_code == 201, response.text


async def test_unsafe_input_is_rejected(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    for image_src in (
        "javascript:alert(1)",
        "data:text/html,hi",
        "//cdn.example/gown.jpg",
        "/images/../../etc/passwd",
        "http://evil.example/gown.jpg",
    ):
        response = await client.post(
            "/api/v1/admin/products",
            headers=auth_headers,
            files=_parts(_product(image_src=image_src, title=f"Bad {image_src[:12]}")),
        )
        assert response.status_code == 422, image_src

    cheap = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(_product(price=200, compare_at_price=100)),
    )
    assert cheap.status_code == 422

    extra = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(_product(role="superadmin")),
    )
    assert extra.status_code == 422

    slug = await client.get("/api/v1/products/not-a-product")
    assert slug.status_code == 422

    huge_page = await client.get("/api/v1/products", params={"page": 10001})
    assert huge_page.status_code == 422

    wide = await client.get(
        "/api/v1/admin/products", headers=auth_headers, params={"page_size": 101}
    )
    assert wide.status_code == 422


async def test_slug_price_and_stock_updates(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await _create(client, auth_headers, title="গাউন")
    second = await _create(client, auth_headers, title="গাউন")
    assert SLUG.fullmatch(first["slug"])
    assert SLUG.fullmatch(second["slug"])
    assert first["slug"] != second["slug"]

    duplicate = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(_product(slug=first["slug"], title="Other")),
    )
    assert duplicate.status_code == 409

    patched = await client.patch(
        f"/api/v1/admin/products/{first['id']}",
        headers=auth_headers,
        files=_parts({"status": "sold-out", "published": False, "price": 12000}),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "sold-out"
    assert patched.json()["published"] is False
    assert patched.json()["slug"] == first["slug"]
    assert patched.json()["content"]["tagline"] == "হাতে তৈরি"

    raised = await client.patch(
        f"/api/v1/admin/products/{first['id']}",
        headers=auth_headers,
        files=_parts({"compare_at_price": 100}),
    )
    assert raised.status_code == 422

    https = await _create(
        client,
        auth_headers,
        title="Remote",
        image_src="https://cdn.example.com/gown.jpg",
        featured=False,
        badge=None,
    )
    assert https["image_src"] == "https://cdn.example.com/gown.jpg"

    deleted = await client.delete(f"/api/v1/admin/products/{second['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/admin/products/{second['id']}", headers=auth_headers)
    assert missing.status_code == 404


async def test_storefront_sort_and_new_arrivals(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create(
        client,
        auth_headers,
        title="Best Lamp",
        category="gadgets",
        price=500,
        badge="Best Seller",
        featured=False,
    )
    await _create(
        client,
        auth_headers,
        title="New Lamp",
        category="gadgets",
        price=100,
        badge="New",
        featured=False,
    )
    await _create(
        client,
        auth_headers,
        title="Plain Lamp",
        category="gadgets",
        price=50,
        badge=None,
        featured=False,
    )

    popular = await client.get(
        "/api/v1/products", params={"sort": "popularity", "category": "gadgets"}
    )
    assert [item["title"] for item in popular.json()["items"]] == [
        "Best Lamp",
        "New Lamp",
        "Plain Lamp",
    ]

    cheapest = await client.get(
        "/api/v1/products", params={"sort": "price-asc", "category": "gadgets"}
    )
    assert [item["title"] for item in cheapest.json()["items"]] == [
        "Plain Lamp",
        "New Lamp",
        "Best Lamp",
    ]

    arrivals = await client.get("/api/v1/products", params={"view": "new"})
    assert [item["title"] for item in arrivals.json()["items"]] == ["New Lamp"]


async def test_create_and_update_upload_the_page_images(
    client: AsyncClient, auth_headers: dict[str, str], tmp_path, monkeypatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "media_root", tmp_path)
    body = _product(title="Uploaded Gown", image_src="")
    created_response = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(
            body,
            images=[
                ("front.jpg", JPEG, "image/jpeg"),
                ("back.jpg", JPEG, "image/jpeg"),
            ],
            alts=["সামনের দিক", "পিছনের দিক"],
            quality=("quality.jpg", JPEG, "image/jpeg"),
            quality_alt="কোয়ালিটি চেক",
        ),
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["image_src"].startswith("/media/products/")
    assert [item["alt"] for item in created["content"]["gallery"]] == [
        "সামনের দিক",
        "পিছনের দিক",
    ]
    assert created["content"]["quality_image_alt"] == "কোয়ালিটি চেক"

    public = await client.get(f"/api/v1/products/{created['id']}")
    assert public.status_code == 200, public.text
    detail = public.json()
    assert len(detail["gallery"]) == 2
    assert detail["gallery"][0]["src"] == created["image_src"]
    assert detail["quality_image_src"] == created["content"]["quality_image_src"]

    rejected = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(
            _product(title="Svg Gown"),
            images=[("icon.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")],
        ),
    )
    assert rejected.status_code == 422

    missing = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(_product(title="No Photo", image_src="")),
    )
    assert missing.status_code == 422

    added = await client.patch(
        f"/api/v1/admin/products/{created['id']}",
        headers=auth_headers,
        files=_parts({}, images=[("side.jpg", JPEG, "image/jpeg")], alts=["পাশ"]),
    )
    assert added.status_code == 200, added.text
    assert [item["alt"] for item in added.json()["content"]["gallery"]] == [
        "সামনের দিক",
        "পিছনের দিক",
        "পাশ",
    ]


AVIF = b"\x00\x00\x00\x20ftypavif\x00\x00\x00\x00avifmif1"


async def test_product_images_reject_avif_and_a_thirteenth_file(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    avif = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(
            _product(title="Avif Gown", image_src=""),
            images=[("photo.avif", AVIF, "image/avif")],
        ),
    )
    assert avif.status_code == 422
    assert "JPEG" in avif.json()["error"]["message"]

    too_many = await client.post(
        "/api/v1/admin/products",
        headers=auth_headers,
        files=_parts(
            _product(title="Too Many Photos", image_src=""),
            images=[(f"{index}.jpg", JPEG, "image/jpeg") for index in range(13)],
        ),
    )
    assert too_many.status_code == 422
    assert "12" in too_many.json()["error"]["message"]


async def test_operations_routes_reject_a_missing_token(client: AsyncClient) -> None:
    missing = "00000000-0000-4000-8000-000000000001"
    checks = [
        ("GET", "/api/v1/admin/orders"),
        ("GET", f"/api/v1/admin/orders/{missing}"),
        ("PATCH", f"/api/v1/admin/orders/{missing}"),
        ("GET", "/api/v1/admin/products"),
        ("POST", "/api/v1/admin/products"),
        ("GET", "/api/v1/admin/carts"),
        ("GET", f"/api/v1/admin/carts/{missing}"),
        ("GET", "/api/v1/admin/delivery"),
        ("PATCH", "/api/v1/admin/delivery"),
    ]
    for method, path in checks:
        response = await client.request(method, path, json={})
        assert response.status_code == 401, (method, path, response.status_code, response.text)
