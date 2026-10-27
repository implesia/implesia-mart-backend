from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.blogs.posts import cover_ref_ok, owns_media, safe_cover

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
POSTS = "/api/v1/admin/pages/blogs/posts"


def _post(category_id: str, **extra: object) -> dict:
    body: dict = {
        "is_active": True,
        "slug": "cover-test",
        "title": "Cover test",
        "excerpt": "Short.",
        "category_id": category_id,
        "cover_image": "/media/blogs/example.jpg",
        "cover_alt": "A cover",
        "tags": [],
        "related_product_slugs": [],
        "blocks": [{"type": "paragraph", "text": "Body.", "is_active": True}],
    }
    body.update(extra)
    return body


async def _category(client: AsyncClient, headers: dict[str, str]) -> str:
    saved = await client.patch(
        "/api/v1/admin/pages/blogs/categories",
        headers=headers,
        json={"is_active": True, "items": [{"label": "Guides", "is_active": True}]},
    )
    assert saved.status_code == 200, saved.text
    return str(saved.json()["items"][0]["id"])


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/media/blogs/a.jpg",
        "/images/blog/a.webp",
        "https://cdn.example.com/a.jpg",
        "http://127.0.0.1:8001/media/blogs/a.jpg",
    ],
)
def test_cover_ref_ok_accepts_renderable_values(value: str) -> None:
    assert cover_ref_ok(value)
    assert safe_cover(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "blob:http://localhost:3000/3f1c2d",
        "data:image/png;base64,AAAA",
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "file:///etc/passwd",
        "vbscript:msgbox",
        "//evil.example/a.jpg",
        "/media/../etc/passwd",
        "https://",
        "ftp://host/a.jpg",
        "relative/a.jpg",
        "/media/blogs/a b.jpg",
        "/media/blogs/a\\b.jpg",
    ],
)
def test_cover_ref_ok_rejects_unusable_values(value: str) -> None:
    assert not cover_ref_ok(value)
    assert safe_cover(value) == ""


def test_owns_media_only_for_blog_uploads() -> None:
    assert owns_media("/media/blogs/a.jpg")
    assert not owns_media("/media/products/a.jpg")
    assert not owns_media("/media/blogs/../products/a.jpg")


async def test_blob_cover_is_rejected_when_saving(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    category_id = await _category(client, auth_headers)
    response = await client.post(
        POSTS,
        headers=auth_headers,
        json=_post(category_id, cover_image="blob:http://localhost:3000/abc"),
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"]


async def test_publishing_needs_a_cover_but_a_hidden_draft_does_not(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    category_id = await _category(client, auth_headers)
    published = await client.post(
        POSTS, headers=auth_headers, json=_post(category_id, cover_image="")
    )
    assert published.status_code == 422
    draft = await client.post(
        POSTS, headers=auth_headers, json=_post(category_id, cover_image="", is_active=False)
    )
    assert draft.status_code == 201, draft.text
    assert draft.json()["cover_needs_upload"] is False


async def test_upload_cover_stores_a_validated_image(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    uploaded = await client.post(
        f"{POSTS}/cover", headers=auth_headers, files={"image": ("c.jpg", JPEG, "image/jpeg")}
    )
    assert uploaded.status_code == 201, uploaded.text
    url = uploaded.json()["url"]
    assert url.startswith("/media/blogs/") and url.endswith(".jpg")
    assert (tmp_path / "blogs" / url.rsplit("/", 1)[1]).read_bytes() == JPEG

    category_id = await _category(client, auth_headers)
    saved = await client.post(POSTS, headers=auth_headers, json=_post(category_id, cover_image=url))
    assert saved.status_code == 201, saved.text
    public = await client.get("/api/v1/pages/blogs/posts/cover-test")
    assert public.json()["cover_image"] == url


async def test_upload_cover_rejects_bad_files_and_anonymous_callers(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    anonymous = await client.post(f"{POSTS}/cover", files={"image": ("c.jpg", JPEG, "image/jpeg")})
    assert anonymous.status_code == 401

    html = await client.post(
        f"{POSTS}/cover",
        headers=auth_headers,
        files={"image": ("c.jpg", b"<html><script>alert(1)</script></html>", "image/jpeg")},
    )
    assert html.status_code == 422

    svg = await client.post(
        f"{POSTS}/cover",
        headers=auth_headers,
        files={"image": ("c.svg", b"<svg onload=alert(1)></svg>", "image/svg+xml")},
    )
    assert svg.status_code == 422

    empty = await client.post(
        f"{POSTS}/cover", headers=auth_headers, files={"image": ("c.jpg", b"", "image/jpeg")}
    )
    assert empty.status_code == 422

    monkeypatch.setattr(settings, "max_image_bytes", 10)
    big = await client.post(
        f"{POSTS}/cover", headers=auth_headers, files={"image": ("c.jpg", JPEG, "image/jpeg")}
    )
    assert big.status_code == 422
    assert not list((tmp_path / "blogs").glob("*")) if (tmp_path / "blogs").exists() else True


async def test_replaced_and_deleted_covers_are_removed_from_disk(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)

    async def upload() -> str:
        reply = await client.post(
            f"{POSTS}/cover", headers=auth_headers, files={"image": ("c.jpg", JPEG, "image/jpeg")}
        )
        assert reply.status_code == 201, reply.text
        return str(reply.json()["url"])

    def exists(url: str) -> bool:
        return (tmp_path / "blogs" / url.rsplit("/", 1)[1]).exists()

    category_id = await _category(client, auth_headers)
    first = await upload()
    created = await client.post(
        POSTS, headers=auth_headers, json=_post(category_id, cover_image=first)
    )
    post_id = created.json()["id"]
    second = await upload()
    updated = await client.patch(
        f"{POSTS}/{post_id}", headers=auth_headers, json=_post(category_id, cover_image=second)
    )
    assert updated.status_code == 200, updated.text
    assert not exists(first)
    assert exists(second)

    deleted = await client.delete(f"{POSTS}/{post_id}", headers=auth_headers)
    assert deleted.status_code == 200
    assert not exists(second)


async def test_seo_fields_round_trip_and_are_validated(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    category_id = await _category(client, auth_headers)
    created = await client.post(
        POSTS,
        headers=auth_headers,
        json=_post(category_id, seo_title="  Best power banks  ", seo_description="Pick one."),
    )
    assert created.status_code == 201, created.text
    assert created.json()["seo_title"] == "Best power banks"
    public = await client.get("/api/v1/pages/blogs/posts/cover-test")
    assert public.json()["seo_description"] == "Pick one."

    too_long = await client.post(
        POSTS, headers=auth_headers, json=_post(category_id, slug="long", seo_title="x" * 71)
    )
    assert too_long.status_code == 422


async def test_control_characters_are_stripped_from_text(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    category_id = await _category(client, auth_headers)
    created = await client.post(
        POSTS,
        headers=auth_headers,
        json=_post(
            category_id,
            title="Clean\x00 title\x07",
            blocks=[{"type": "paragraph", "text": "Line one\nLine two\x00", "is_active": True}],
        ),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["title"] == "Clean title"
    assert body["blocks"][0]["text"] == "Line one\nLine two"


async def test_script_text_is_stored_as_inert_text(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Body blocks are plain text; the storefront renders them as text nodes, never HTML."""
    category_id = await _category(client, auth_headers)
    payload = "<script>alert(1)</script>"
    created = await client.post(
        POSTS,
        headers=auth_headers,
        json=_post(
            category_id,
            blocks=[{"type": "paragraph", "text": payload, "is_active": True}],
        ),
    )
    assert created.status_code == 201, created.text
    public = await client.get("/api/v1/pages/blogs/posts/cover-test")
    assert public.headers["content-type"].startswith("application/json")
    assert public.json()["blocks"][0]["text"] == payload


async def test_legacy_blob_cover_is_hidden_on_read_and_stays_editable(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    from sqlalchemy import select

    from app.models.blogs.posts import BlogPost

    category_id = await _category(client, auth_headers)
    created = await client.post(POSTS, headers=auth_headers, json=_post(category_id))
    assert created.status_code == 201, created.text
    post = await db_session.scalar(select(BlogPost).where(BlogPost.slug == "cover-test"))
    assert post is not None
    post.cover_image = "blob:http://localhost:3000/legacy"
    await db_session.commit()

    public = await client.get("/api/v1/pages/blogs/posts/cover-test")
    assert public.status_code == 200
    assert public.json()["cover_image"] == ""
    listing = await client.get("/api/v1/pages/blogs/posts")
    assert listing.json()["posts"][0]["cover_image"] == ""

    admin = await client.get(POSTS, headers=auth_headers)
    row = admin.json()["posts"][0]
    assert row["cover_needs_upload"] is True
    assert row["cover_image"] == ""

    hidden = await client.patch(
        f"{POSTS}/{row['id']}",
        headers=auth_headers,
        json=_post(category_id, cover_image="", is_active=False, title="Edited"),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["cover_needs_upload"] is False
