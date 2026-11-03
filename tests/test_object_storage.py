"""Object storage for uploads: R2 when configured, the local disk otherwise."""

from typing import Any

import pytest
from botocore.exceptions import ClientError
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.exceptions import UnprocessableError
from app.services import image_storage
from app.services.image_storage import delete_owned_media, safe_object_key, store_image, store_video

PRODUCTION_SECRET = "production-secret-key-with-enough-length"
JPEG = b"\xff\xd8\xff\x00"
PNG = b"\x89PNG\r\n\x1a\n\x00"
GIF = b"GIF89a\x00"
WEBP = b"RIFF\x00\x00\x00\x00WEBP"
MP4 = b"\x00\x00\x00\x18ftypisom\x00"
WEBM = b"\x1a\x45\xdf\xa3webm"


class FakeS3:
    def __init__(self, *, fail: str = "") -> None:
        self.puts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.fail = fail

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail == "put":
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "PutObject")
        self.puts.append(kwargs)
        return {}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail == "delete":
            raise ClientError({"Error": {"Code": "InternalError", "Message": "no"}}, "DeleteObject")
        self.deletes.append(kwargs)
        return {}


def _r2_settings(**extra: str) -> dict[str, str]:
    values = {
        "s3_endpoint_url": "https://account.r2.cloudflarestorage.com",
        "s3_bucket": "implesia-mart-media",
        "s3_access_key_id": "test-access-key",
        "s3_secret_access_key": "test-secret-key",
        "media_public_base_url": "https://media.implesia.com",
    }
    values.update(extra)
    return values


def _enable_r2(monkeypatch: pytest.MonkeyPatch, fake: FakeS3) -> None:
    monkeypatch.setattr(
        image_storage.settings, "s3_endpoint_url", "https://account.r2.cloudflarestorage.com"
    )
    monkeypatch.setattr(image_storage.settings, "s3_bucket", "implesia-mart-media")
    monkeypatch.setattr(image_storage.settings, "s3_access_key_id", SecretStr("test-access-key"))
    monkeypatch.setattr(
        image_storage.settings, "s3_secret_access_key", SecretStr("test-secret-key")
    )
    monkeypatch.setattr(
        image_storage.settings, "media_public_base_url", "https://media.implesia.com"
    )
    monkeypatch.setattr(image_storage, "_s3", lambda: fake)


def test_disk_is_used_when_s3_settings_are_empty(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_storage.settings, "media_root", tmp_path)
    url = store_image(JPEG)
    assert url.startswith("/media/products/")
    assert url.endswith(".jpg")
    stored = tmp_path / url.removeprefix("/media/")
    assert stored.is_file()
    assert stored.read_bytes() == JPEG


def test_r2_put_uses_the_folder_key_and_content_type(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_storage.settings, "media_root", tmp_path)
    fake = FakeS3()
    _enable_r2(monkeypatch, fake)
    cases = (
        (store_image, JPEG, "products", ".jpg", "image/jpeg"),
        (store_image, PNG, "banners", ".png", "image/png"),
        (store_image, GIF, "reviews", ".gif", "image/gif"),
        (store_image, WEBP, "blogs", ".webp", "image/webp"),
        (store_video, MP4, "home-media", ".mp4", "video/mp4"),
        (store_video, WEBM, "products", ".webm", "video/webm"),
    )
    for store, data, folder, suffix, _content_type in cases:
        url = store(data, folder=folder)
        assert url.startswith(f"/media/{folder}/")
        assert url.endswith(suffix)
        assert not (tmp_path / url.removeprefix("/media/")).exists()
    assert len(fake.puts) == len(cases)
    for saved, (_, _, folder, suffix, content_type) in zip(fake.puts, cases, strict=True):
        assert saved["Bucket"] == "implesia-mart-media"
        assert saved["Key"].startswith(f"{folder}/")
        assert saved["Key"].endswith(suffix)
        assert "/media/" not in saved["Key"]
        assert saved["ContentType"] == content_type
        assert saved["CacheControl"] == image_storage._CACHE_CONTROL
        assert saved["Body"]


def test_r2_delete_removes_the_same_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeS3()
    _enable_r2(monkeypatch, fake)
    delete_owned_media(
        {
            "/media/products/abc.jpg",
            "/media/banners/other.jpg",
            "/media/products/../secrets.txt",
            "https://evil.example/products/abc.jpg",
            "",
        }
    )
    assert fake.deletes == [
        {"Bucket": "implesia-mart-media", "Key": "products/abc.jpg"},
    ]


def test_disk_delete_still_unlinks_the_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_storage.settings, "media_root", tmp_path)
    url = store_image(JPEG, folder="about")
    path = tmp_path / url.removeprefix("/media/")
    assert path.is_file()
    delete_owned_media({url}, folder="about")
    assert not path.exists()


def test_svg_and_html_are_rejected_before_any_upload(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_storage.settings, "media_root", tmp_path)
    fake = FakeS3()
    _enable_r2(monkeypatch, fake)
    for payload in (
        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        b"<html><script>alert(1)</script></html>",
        b"<?xml version='1.0'?><svg></svg>",
    ):
        with pytest.raises(UnprocessableError):
            store_image(payload)
    assert fake.puts == []
    assert list(tmp_path.rglob("*")) == []


def test_storage_failure_does_not_report_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_r2(monkeypatch, FakeS3(fail="put"))
    with pytest.raises(RuntimeError, match="Could not store"):
        store_image(JPEG)
    _enable_r2(monkeypatch, FakeS3(fail="delete"))
    with pytest.raises(RuntimeError, match="Could not delete"):
        delete_owned_media({"/media/products/abc.jpg"})


def test_safe_object_key_rejects_escapes() -> None:
    assert safe_object_key("/products/abc.jpg") == "products/abc.jpg"
    assert safe_object_key("home-media/clip.mp4") == "home-media/clip.mp4"
    for path in (
        "../etc/passwd",
        "products/../../etc/passwd",
        "products/%2e%2e/passwd",
        "products/%252e%252e/passwd",
        "https://evil.example/a.jpg",
        "//evil.example/a.jpg",
        "not-a-folder/a.jpg",
        "products/a.jpg/extra",
        "products/.hidden.jpg",
        "products/a b.jpg",
        "",
    ):
        assert safe_object_key(path) is None


def test_partial_s3_settings_are_rejected() -> None:
    with pytest.raises(ValidationError, match="set together"):
        Settings(s3_bucket="implesia-mart-media")


def test_production_public_url_must_be_https_without_secrets() -> None:
    with pytest.raises(ValidationError, match="MEDIA_PUBLIC_BASE_URL must use https"):
        Settings(
            environment="production",
            secret_key=PRODUCTION_SECRET,
            **_r2_settings(media_public_base_url="http://media.implesia.com"),
        )
    with pytest.raises(ValidationError, match="must not include credentials"):
        Settings(**_r2_settings(media_public_base_url="https://user:pw@media.implesia.com"))
    with pytest.raises(ValidationError, match="must not include a path"):
        Settings(**_r2_settings(media_public_base_url="https://media.implesia.com/files"))


def test_complete_s3_settings_enable_object_storage() -> None:
    settings = Settings(**_r2_settings())
    assert settings.object_storage_enabled


def test_empty_s3_settings_stay_on_disk() -> None:
    settings = Settings()
    assert not settings.object_storage_enabled


async def test_media_redirects_to_the_public_bucket(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_r2(monkeypatch, FakeS3())
    ok = await client.get("/media/products/abc123.jpg?v=restore", follow_redirects=False)
    assert ok.status_code == 307
    assert ok.headers["location"] == "https://media.implesia.com/products/abc123.jpg?v=restore"

    head = await client.head("/media/home-media/clip.mp4", follow_redirects=False)
    assert head.status_code == 307
    assert head.headers["location"] == "https://media.implesia.com/home-media/clip.mp4"

    posted = await client.post("/media/products/abc123.jpg")
    assert posted.status_code == 405

    for path in (
        "/media/../etc/passwd",
        "/media/products/%2e%2e/%2e%2e/etc/passwd",
        "/media/not-a-folder/a.jpg",
        "/media/products/a.jpg/extra",
    ):
        blocked = await client.get(path, follow_redirects=False)
        assert blocked.status_code == 404
        assert "location" not in blocked.headers


async def test_local_media_is_still_served_from_disk(
    client, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_storage.settings, "media_root", tmp_path)
    folder = tmp_path / "products"
    folder.mkdir()
    (folder / "abc.jpg").write_bytes(JPEG)
    response = await client.get("/media/products/abc.jpg")
    assert response.status_code == 200
    assert response.content == JPEG
