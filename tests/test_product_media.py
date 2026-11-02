"""Gallery videos: uploaded MP4/WEBM files and YouTube links, next to photos."""

import json
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.schemas.product import GalleryImage, youtube_id
from tests.test_products import JPEG, _parts, _product

ADMIN = "/api/v1/admin/products"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\x82\x84webm" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.mark.parametrize(
    "link",
    [
        "dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s",
        "https://youtu.be/dQw4w9WgXcQ?si=abc",
        "youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
    ],
)
def test_youtube_links_resolve_to_the_id(link: str) -> None:
    assert youtube_id(link) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=short",
        "https://youtube.com/channel/dQw4w9WgXcQ",
        "javascript:alert(1)",
        "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
    ],
)
def test_bad_youtube_links_are_refused(link: str) -> None:
    with pytest.raises(ValueError):
        youtube_id(link)


def test_old_gallery_items_are_images() -> None:
    item = GalleryImage.model_validate({"src": "/media/products/a.jpg", "alt": "A"})
    assert item.kind == "image" and item.youtube_id == ""
    video = GalleryImage.model_validate({"kind": "video", "src": "/media/products/a.mp4"})
    assert video.kind == "video"
    with pytest.raises(ValueError):
        GalleryImage.model_validate({"kind": "video", "src": "/media/products/a.jpg"})


async def test_videos_and_youtube_reach_the_product_page(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    body = _product(
        content={
            "gallery": [
                {"src": "/images/products/gown.jpg", "alt": "Front"},
                {"kind": "youtube", "youtube_id": "https://youtu.be/dQw4w9WgXcQ", "alt": "Demo"},
            ]
        }
    )
    parts = _parts(body)
    parts.append(("videos", ("clip.mp4", MP4, "video/mp4")))
    parts.append(("videos", ("clip.webm", WEBM, "video/webm")))
    parts.append(("video_alts", (None, json.dumps(["Unboxing", ""]))))
    response = await client.post(ADMIN, headers=auth_headers, files=parts)
    assert response.status_code == 201, response.text
    gallery = response.json()["content"]["gallery"]
    assert [item["kind"] for item in gallery] == ["image", "youtube", "video", "video"]
    assert gallery[1]["youtube_id"] == "dQw4w9WgXcQ" and gallery[1]["src"] == ""
    assert gallery[2]["src"].endswith(".mp4") and gallery[2]["alt"] == "Unboxing"
    assert gallery[3]["src"].endswith(".webm")
    assert len(list((tmp_path / "products").iterdir())) == 2

    public = (await client.get(f"/api/v1/products/{response.json()['id']}")).json()
    assert [item["kind"] for item in public["gallery"]] == ["image", "youtube", "video", "video"]
    assert public["gallery"][1]["youtube_id"] == "dQw4w9WgXcQ"


async def test_video_uploads_are_checked(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)

    async def post(video: tuple[str, bytes, str]) -> list[dict]:
        parts = _parts(_product())
        parts.append(("videos", video))
        response = await client.post(ADMIN, headers=auth_headers, files=parts)
        assert response.status_code == 400, response.text
        return response.json()["errors"]

    wrong_name = await post(("clip.mov", MP4, "video/mp4"))
    assert wrong_name[0]["message"] == "এই ধরনের ভিডিও নেওয়া যায় না"
    fake = await post(("clip.mp4", b"<html>not a video</html>", "video/mp4"))
    assert fake[0]["message"] == "এই ধরনের ভিডিও নেওয়া যায় না"
    monkeypatch.setattr(settings, "max_video_bytes", 32)
    big = await post(("clip.mp4", MP4, "video/mp4"))
    assert big[0]["message"] == "ভিডিওর সাইজ অনেক বড়"
    assert not (tmp_path / "products").exists() or not any((tmp_path / "products").iterdir())

    bad_link = await client.post(
        ADMIN,
        headers=auth_headers,
        files=_parts(
            _product(
                content={"gallery": [{"kind": "youtube", "youtube_id": "https://vimeo.com/1"}]}
            )
        ),
    )
    assert bad_link.status_code == 400
    assert bad_link.json()["errors"][0]["message"] == "YouTube লিংকটা সঠিক নয়"


async def test_a_video_never_becomes_the_main_image(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    parts = _parts(_product(published=False, image_src=""))
    parts.append(("videos", ("clip.mp4", MP4, "video/mp4")))
    response = await client.post(ADMIN, headers=auth_headers, files=parts)
    assert response.status_code == 201, response.text
    assert response.json()["image_src"] == ""


def _files(root: Path) -> set[str]:
    folder = root / "products"
    return {path.name for path in folder.iterdir()} if folder.exists() else set()


def test_photos_never_keep_a_thumbnail() -> None:
    item = GalleryImage.model_validate(
        {"src": "/media/products/a.jpg", "thumbnail": "/media/products/b.jpg"}
    )
    assert item.thumbnail == ""


async def test_custom_thumbnails_are_saved_replaced_and_removed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)
    body = _product(
        content={"gallery": [{"id": "gallery-yt1", "kind": "youtube", "youtube_id": "dQw4w9WgXcQ"}]}
    )
    parts = _parts(body)
    parts.append(("videos", ("clip.mp4", MP4, "video/mp4")))
    parts.append(("thumbnails", ("yt.jpg", JPEG, "image/jpeg")))
    parts.append(("thumbnails", ("clip.jpg", JPEG, "image/jpeg")))
    parts.append(("thumbnail_targets", (None, json.dumps(["gallery-yt1", "video:0"]))))
    response = await client.post(ADMIN, headers=auth_headers, files=parts)
    assert response.status_code == 201, response.text
    product = response.json()
    gallery = product["content"]["gallery"]
    yt_thumb, video_thumb = gallery[0]["thumbnail"], gallery[1]["thumbnail"]
    assert yt_thumb.startswith("/media/products/") and yt_thumb.endswith(".jpg")
    assert video_thumb.startswith("/media/products/") and video_thumb != yt_thumb
    assert len(_files(tmp_path)) == 3

    public = (await client.get(f"/api/v1/products/{product['id']}")).json()
    playable = [item for item in public["gallery"] if item["kind"] != "image"]
    assert [item["thumbnail"] for item in playable] == [yt_thumb, video_thumb]

    # Replace the video thumbnail and remove the YouTube one.
    kept = [
        {**gallery[0], "thumbnail": ""},
        {**gallery[1], "thumbnail": ""},
    ]
    patch = [
        ("payload", (None, json.dumps({"content": {**product["content"], "gallery": kept}}))),
        ("thumbnails", ("new.png", PNG, "image/png")),
        ("thumbnail_targets", (None, json.dumps([gallery[1]["id"]]))),
    ]
    updated = await client.patch(f"{ADMIN}/{product['id']}", headers=auth_headers, files=patch)
    assert updated.status_code == 200, updated.text
    after = updated.json()["content"]["gallery"]
    assert after[0]["thumbnail"] == ""
    assert after[1]["thumbnail"].endswith(".png")
    names = _files(tmp_path)
    assert yt_thumb.rsplit("/", 1)[1] not in names
    assert video_thumb.rsplit("/", 1)[1] not in names
    assert after[1]["thumbnail"].rsplit("/", 1)[1] in names and len(names) == 2

    await client.delete(f"{ADMIN}/{product['id']}", headers=auth_headers)
    assert _files(tmp_path) == set()


async def test_thumbnail_uploads_are_checked(
    client: AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "media_root", tmp_path)

    async def post(thumb: tuple[str, bytes, str], targets: list[str]) -> list[dict]:
        parts = _parts(
            _product(
                content={
                    "gallery": [
                        {"id": "gallery-photo", "src": "/images/products/gown.jpg"},
                        {"id": "gallery-yt1", "kind": "youtube", "youtube_id": "dQw4w9WgXcQ"},
                    ]
                }
            )
        )
        parts.append(("thumbnails", thumb))
        parts.append(("thumbnail_targets", (None, json.dumps(targets))))
        response = await client.post(ADMIN, headers=auth_headers, files=parts)
        assert response.status_code == 400, response.text
        return response.json()["errors"]

    not_image = await post(("a.jpg", b"<html></html>", "image/jpeg"), ["gallery-yt1"])
    assert not_image[0]["message"] == "এই ধরনের ছবি নেওয়া যায় না"
    no_match = "থাম্বনেইলটা কোনো ভিডিওর সাথে মেলেনি"
    assert (await post(("a.jpg", JPEG, "image/jpeg"), ["gallery-nope"]))[0]["message"] == no_match
    assert (await post(("a.jpg", JPEG, "image/jpeg"), ["gallery-photo"]))[0]["message"] == no_match
    assert (await post(("a.jpg", JPEG, "image/jpeg"), ["video:0"]))[0]["message"] == no_match
    assert (await post(("a.jpg", JPEG, "image/jpeg"), []))[0]["message"] == no_match
    assert _files(tmp_path) == set()
