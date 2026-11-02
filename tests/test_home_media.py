"""Home media section (image, uploaded video or YouTube) above the testimonials."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.home.media import HomeMedia
from tests.test_home_promo import JPEG
from tests.test_product_media import MP4

PUBLIC = "/api/v1/home/media"
ADMIN = "/api/v1/admin/home/media"


def _body(**extra: object) -> dict:
    body: dict = {
        "is_active": True,
        "heading": "See it in action",
        "subheading": "A quick look",
        "media_type": "image",
        "image_src": "/media/home-media/example.jpg",
        "video_src": "",
        "youtube_url": "",
        "thumbnail_src": "",
        "media_alt": "Products on a shelf",
        "description": "Short description",
        "cta_enabled": True,
        "cta_label": "Shop now",
        "cta_href": "/products",
    }
    body.update(extra)
    return body


async def test_nothing_is_shown_until_the_section_is_published(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    empty = await client.get(PUBLIC)
    assert empty.status_code == 200 and empty.json() is None
    assert empty.headers["cache-control"] == "no-store"
    admin = await client.get(ADMIN, headers=auth_headers)
    assert admin.status_code == 200
    assert admin.json()["is_active"] is False and admin.json()["media_type"] == "image"

    saved = await client.put(ADMIN, headers=auth_headers, json=_body())
    assert saved.status_code == 200, saved.text
    live = (await client.get(PUBLIC)).json()
    assert live["heading"] == "See it in action"
    assert live["image_src"] == "/media/home-media/example.jpg"
    assert live["cta_href"] == "/products" and "is_active" not in live

    hidden = await client.put(ADMIN, headers=auth_headers, json=_body(is_active=False))
    assert hidden.status_code == 200
    assert (await client.get(PUBLIC)).json() is None
    assert (await client.get(ADMIN, headers=auth_headers)).json()["heading"] == "See it in action"


@pytest.mark.parametrize(
    "link",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "dQw4w9WgXcQ",
    ],
)
async def test_youtube_links_are_stored_as_the_video_id(
    client: AsyncClient, auth_headers: dict[str, str], link: str
) -> None:
    saved = await client.put(
        ADMIN,
        headers=auth_headers,
        json=_body(media_type="youtube", youtube_url=link, thumbnail_src="/media/home-media/t.jpg"),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["youtube_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    live = (await client.get(PUBLIC)).json()
    assert live["media_type"] == "youtube" and live["youtube_id"] == "dQw4w9WgXcQ"
    # The image of another type is not kept.
    assert live["image_src"] == "" and live["thumbnail_src"] == "/media/home-media/t.jpg"


async def test_a_disabled_button_is_not_shown_publicly(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    saved = await client.put(ADMIN, headers=auth_headers, json=_body(cta_enabled=False))
    assert saved.status_code == 200
    assert saved.json()["cta_label"] == "Shop now"  # kept for the editor
    live = (await client.get(PUBLIC)).json()
    assert live["cta_label"] == "" and live["cta_href"] == ""


@pytest.mark.parametrize(
    "extra",
    [
        {"heading": ""},
        {"image_src": ""},
        {"media_alt": ""},
        {"media_type": "audio"},
        {"media_type": "video", "video_src": ""},
        {"media_type": "video", "video_src": "/media/home-media/clip.mov"},
        {"media_type": "youtube", "youtube_url": ""},
        {"media_type": "youtube", "youtube_url": "https://vimeo.com/123"},
        {"youtube_url": "https://www.youtube.com/watch?v=short"},
        {"image_src": "javascript:alert(1)"},
        {"thumbnail_src": "blob:http://localhost:3000/x"},
        {"cta_href": "http://example.com"},
        {"cta_href": "javascript:alert(1)"},
        {"cta_href": "//evil.example"},
        {"cta_href": "/a/../admin"},
        {"cta_href": "https://"},
        {"cta_label": ""},
        {"cta_href": ""},
        {"description": "x" * 501},
        {"unknown": 1},
    ],
)
async def test_invalid_sections_are_rejected_with_the_error_envelope(
    client: AsyncClient, auth_headers: dict[str, str], extra: dict
) -> None:
    response = await client.put(ADMIN, headers=auth_headers, json=_body(**extra))
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"]


async def test_https_buttons_and_hidden_drafts_are_accepted(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    ok = await client.put(
        ADMIN, headers=auth_headers, json=_body(cta_href="https://example.com/sale?x=1")
    )
    assert ok.status_code == 200
    draft = await client.put(
        ADMIN,
        headers=auth_headers,
        json=_body(is_active=False, heading="", image_src="", cta_enabled=False, cta_href=""),
    )
    assert draft.status_code == 200


async def test_admin_endpoints_reject_anonymous_callers(client: AsyncClient) -> None:
    assert (await client.get(ADMIN)).status_code == 401
    assert (await client.put(ADMIN, json=_body())).status_code == 401
    image = {"image": ("c.jpg", JPEG, "image/jpeg")}
    assert (await client.post(f"{ADMIN}/image", files=image)).status_code == 401
    video = {"video": ("c.mp4", MP4, "video/mp4")}
    assert (await client.post(f"{ADMIN}/video", files=video)).status_code == 401


async def test_uploads_validate_type_and_size(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    video = await client.post(
        f"{ADMIN}/video", headers=auth_headers, files={"video": ("c.mp4", MP4, "video/mp4")}
    )
    assert video.status_code == 201, video.text
    url = video.json()["url"]
    assert url.startswith("/media/home-media/") and url.endswith(".mp4")
    assert (tmp_path / "home-media" / url.rsplit("/", 1)[1]).read_bytes() == MP4

    image = await client.post(
        f"{ADMIN}/image", headers=auth_headers, files={"image": ("t.jpg", JPEG, "image/jpeg")}
    )
    assert image.status_code == 201 and image.json()["url"].startswith("/media/home-media/")

    wrong = await client.post(
        f"{ADMIN}/video", headers=auth_headers, files={"video": ("c.mov", MP4, "video/quicktime")}
    )
    assert wrong.status_code == 422
    fake = await client.post(
        f"{ADMIN}/video", headers=auth_headers, files={"video": ("c.mp4", b"<html>", "video/mp4")}
    )
    assert fake.status_code == 422
    monkeypatch.setattr(settings, "max_video_bytes", 32)
    big = await client.post(
        f"{ADMIN}/video", headers=auth_headers, files={"video": ("c.mp4", MP4, "video/mp4")}
    )
    assert big.status_code == 422


async def test_replaced_and_dropped_files_are_removed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)

    async def upload(kind: str, name: str, data: bytes, mime: str) -> str:
        response = await client.post(
            f"{ADMIN}/{kind}", headers=auth_headers, files={kind: (name, data, mime)}
        )
        assert response.status_code == 201, response.text
        return str(response.json()["url"])

    def path(url: str) -> Path:
        return tmp_path / "home-media" / url.rsplit("/", 1)[1]

    video_a = await upload("video", "a.mp4", MP4, "video/mp4")
    video_b = await upload("video", "b.mp4", MP4, "video/mp4")
    poster = await upload("image", "p.jpg", JPEG, "image/jpeg")
    image = await upload("image", "i.jpg", JPEG, "image/jpeg")

    as_video = {"media_type": "video", "image_src": "", "thumbnail_src": poster}
    first = await client.put(ADMIN, headers=auth_headers, json=_body(**as_video, video_src=video_a))
    assert first.status_code == 200, first.text
    live = (await client.get(PUBLIC)).json()
    assert live["video_src"] == video_a and live["thumbnail_src"] == poster

    await client.put(ADMIN, headers=auth_headers, json=_body(**as_video, video_src=video_b))
    assert not path(video_a).exists() and path(video_b).exists() and path(poster).exists()

    # Switching to an image drops the video and its poster.
    switched = await client.put(ADMIN, headers=auth_headers, json=_body(image_src=image))
    assert switched.status_code == 200
    assert not path(video_b).exists() and not path(poster).exists() and path(image).exists()
    assert switched.json()["video_src"] == "" and switched.json()["thumbnail_src"] == ""


async def test_unusable_stored_media_is_hidden_publicly_and_flagged_for_editors(
    client: AsyncClient, auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    assert (await client.put(ADMIN, headers=auth_headers, json=_body())).status_code == 200
    await db_session.execute(update(HomeMedia).values(image_src="blob:http://x/legacy"))
    await db_session.commit()
    assert (await client.get(PUBLIC)).json() is None
    admin = (await client.get(ADMIN, headers=auth_headers)).json()
    assert admin["image_src"] == "" and admin["media_needs_upload"] is True
