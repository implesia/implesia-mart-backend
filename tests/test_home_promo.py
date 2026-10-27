from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.home.promo import HomePromo

JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
)
PUBLIC = "/api/v1/home/promo"
ADMIN = "/api/v1/admin/home/promo"


def _body(**extra: object) -> dict:
    body: dict = {
        "is_active": True,
        "eyebrow": "",
        "heading": "Browse the collection",
        "body": "",
        "cta_label": "Shop now",
        "cta_href": "/products",
        "image_src": "/media/promo/example.jpg",
        "image_alt": "Shelves of products",
        "focal_x": 50,
        "focal_y": 50,
        "tone": "dark",
    }
    body.update(extra)
    return body


async def test_nothing_is_shown_until_a_banner_is_published(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get(PUBLIC)).json() is None
    admin = await client.get(ADMIN, headers=auth_headers)
    assert admin.status_code == 200
    assert admin.json()["is_active"] is False and admin.json()["heading"] == ""


async def test_publish_read_hide_round_trip(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.put(ADMIN, headers=auth_headers, json=_body())
    assert saved.status_code == 200, saved.text
    live = (await client.get(PUBLIC)).json()
    assert live["heading"] == "Browse the collection"
    assert live["cta_href"] == "/products" and live["tone"] == "dark"
    assert "is_active" not in live

    hidden = await client.put(ADMIN, headers=auth_headers, json=_body(is_active=False))
    assert hidden.status_code == 200
    assert (await client.get(PUBLIC)).json() is None
    assert hidden.json()["heading"] == "Browse the collection"  # kept for editing


@pytest.mark.parametrize(
    "extra",
    [
        {"image_src": ""},
        {"image_alt": ""},
        {"image_src": "blob:http://localhost:3000/abc"},
        {"image_src": "javascript:alert(1)"},
        {"cta_href": "javascript:alert(1)"},
        {"cta_href": "//evil.example"},
        {"cta_label": ""},
        {"cta_href": ""},
        {"focal_x": 101},
        {"focal_y": -1},
        {"tone": "neon"},
        {"heading": "x" * 121},
        {"unknown": 1},
    ],
)
async def test_invalid_banners_are_rejected_with_the_error_envelope(
    client: AsyncClient, auth_headers: dict[str, str], extra: dict
) -> None:
    response = await client.put(ADMIN, headers=auth_headers, json=_body(**extra))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"]


async def test_a_hidden_draft_may_be_incomplete_but_not_unsafe(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    draft = await client.put(
        ADMIN, headers=auth_headers, json=_body(is_active=False, image_src="", image_alt="")
    )
    assert draft.status_code == 200
    bad = await client.put(
        ADMIN, headers=auth_headers, json=_body(is_active=False, image_src="data:text/html,x")
    )
    assert bad.status_code == 422


async def test_text_is_inert_and_control_characters_are_stripped(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.put(
        ADMIN, headers=auth_headers, json=_body(heading="<script>alert(1)</script>\x00Hi")
    )
    assert saved.status_code == 200
    assert (await client.get(PUBLIC)).json()["heading"] == "<script>alert(1)</script>Hi"


async def test_admin_only_endpoints_reject_anonymous_callers(client: AsyncClient) -> None:
    assert (await client.get(ADMIN)).status_code == 401
    assert (await client.put(ADMIN, json=_body())).status_code == 401
    files = {"image": ("c.jpg", JPEG, "image/jpeg")}
    assert (await client.post(f"{ADMIN}/image", files=files)).status_code == 401


async def test_upload_validates_by_content_and_serves_the_stored_path(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    ok = await client.post(
        f"{ADMIN}/image", headers=auth_headers, files={"image": ("c.jpg", JPEG, "image/jpeg")}
    )
    assert ok.status_code == 201, ok.text
    url = ok.json()["url"]
    assert url.startswith("/media/promo/") and url.endswith(".jpg")
    assert (tmp_path / "promo" / url.rsplit("/", 1)[1]).read_bytes() == JPEG

    html = await client.post(
        f"{ADMIN}/image",
        headers=auth_headers,
        files={"image": ("c.png", b"<html><script>1</script></html>", "image/png")},
    )
    assert html.status_code == 422
    empty = await client.post(
        f"{ADMIN}/image", headers=auth_headers, files={"image": ("c.png", b"", "image/png")}
    )
    assert empty.status_code == 422


async def test_replacing_the_image_removes_the_old_file_only(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    urls = []
    for name in ("a.jpg", "b.jpg"):
        up = await client.post(
            f"{ADMIN}/image", headers=auth_headers, files={"image": (name, JPEG, "image/jpeg")}
        )
        urls.append(up.json()["url"])
    first, second = (tmp_path / "promo" / u.rsplit("/", 1)[1] for u in urls)
    assert (
        await client.put(ADMIN, headers=auth_headers, json=_body(image_src=urls[0]))
    ).status_code == 200
    assert first.exists()
    assert (
        await client.put(ADMIN, headers=auth_headers, json=_body(image_src=urls[1]))
    ).status_code == 200
    assert not first.exists() and second.exists()
    # Saving again with the same image keeps it.
    assert (
        await client.put(ADMIN, headers=auth_headers, json=_body(image_src=urls[1]))
    ).status_code == 200
    assert second.exists()


async def test_unusable_stored_image_is_hidden_publicly_and_flagged_for_editors(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    assert (await client.put(ADMIN, headers=auth_headers, json=_body())).status_code == 200
    await db_session.execute(update(HomePromo).values(image_src="blob:http://x/legacy"))
    await db_session.commit()
    assert (await client.get(PUBLIC)).json() is None
    admin = (await client.get(ADMIN, headers=auth_headers)).json()
    assert admin["image_src"] == "" and admin["image_needs_upload"] is True
