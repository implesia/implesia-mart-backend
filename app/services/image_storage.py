"""Store uploaded images and videos.

Bytes are identified by signature, not by the client-supplied type. The stored
name is generated. SVG, HTML, and any other executable content are rejected.

When the S3 settings are set, the bytes go to that bucket (Cloudflare R2 in
production). The object key is `<folder>/<name>`, the same layout the disk
used, and the value saved in the database stays `/media/<folder>/<name>`.
When those settings are empty, the bytes are written under `media_root`.
Tests and local development use that disk path.
"""

import re
import uuid
from typing import Any
from urllib.parse import unquote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import UnprocessableError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Filenames are a generated id plus a sniffed suffix. Nothing else is served.
_OBJECT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
# The name is a UUID, so a replaced file is a new object. Browsers and the
# public media host can keep this copy forever.
_CACHE_CONTROL = "public, max-age=31536000, immutable"

_MAX_FILES = 12
_READ = 64 * 1024
_FOLDERS = frozenset(
    {
        "products",
        "banners",
        "categories",
        "reviews",
        "about",
        "sustainability",
        "blogs",
        "promo",
        "home-media",
        "footer",
    }
)

# (signature, suffix). WebP is checked separately because the mark is not a prefix.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


_VIDEO_TYPES = frozenset({"video/mp4", "video/webm", "application/octet-stream", ""})


def sniff_video(data: bytes) -> str:
    """MP4 has an `ftyp` box at byte 4. WebM is EBML with the `webm` doc type."""
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return ".mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in data[:64]:
        return ".webm"
    raise UnprocessableError("Video must be an MP4 or WEBM file")


async def read_video(upload: UploadFile) -> bytes:
    name = (upload.filename or "").lower()
    if not name.endswith((".mp4", ".webm")):
        raise UnprocessableError("Video must be an MP4 or WEBM file")
    if (upload.content_type or "").split(";")[0].strip().lower() not in _VIDEO_TYPES:
        raise UnprocessableError("Video must be an MP4 or WEBM file")
    chunks: list[bytes] = []
    total = 0
    limit = settings.max_video_bytes
    while True:
        chunk = await upload.read(_READ * 16)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise UnprocessableError("Video is too large")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise UnprocessableError("Video is empty")
    sniff_video(data)
    return data


def store_video(data: bytes, *, folder: str = "products") -> str:
    return _write(data, _folder(folder), sniff_video(data))


def sniff_image(data: bytes) -> str:
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    for signature, suffix in _SIGNATURES:
        if data.startswith(signature):
            return suffix
    raise UnprocessableError("Image must be a JPEG, PNG, WEBP, or GIF")


async def read_image(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    limit = settings.max_image_bytes
    while True:
        chunk = await upload.read(_READ)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise UnprocessableError("Image is too large")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise UnprocessableError("Image is empty")
    sniff_image(data)
    return data


def _folder(name: str) -> str:
    if name not in _FOLDERS:
        raise ValueError(f"Unknown media folder: {name}")
    return name


def store_image(data: bytes, *, folder: str = "products") -> str:
    return _write(data, _folder(folder), sniff_image(data))


def _content_type(suffix: str) -> str:
    try:
        return _CONTENT_TYPES[suffix]
    except KeyError as exc:
        raise UnprocessableError("Unsupported media type") from exc


def _write(data: bytes, folder: str, suffix: str) -> str:
    name = f"{uuid.uuid4().hex}{suffix}"
    key = f"{folder}/{name}"
    if settings.object_storage_enabled:
        _put_object(key, data, _content_type(suffix))
    else:
        directory = (settings.media_root / folder).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(data)
    return f"/media/{key}"


def delete_owned_media(refs: set[str], *, folder: str = "products") -> None:
    folder = _folder(folder)
    prefix = f"/media/{folder}/"
    root = (settings.media_root / folder).resolve()
    remote = settings.object_storage_enabled
    for ref in refs:
        if not ref.startswith(prefix):
            continue
        name = ref.removeprefix(prefix)
        if not name or "/" in name or "\\" in name or name.startswith("."):
            continue
        if remote:
            _delete_object(f"{folder}/{name}")
            continue
        path = (root / name).resolve()
        if path.parent != root:
            continue
        path.unlink(missing_ok=True)


def safe_object_key(path: str) -> str | None:
    """`folder/name` for a public media URL, or None when the path is unsafe.

    Used by the `/media` redirect so a request cannot leave the public host
    or address a folder this API does not own.
    """
    text = path.strip()
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    if text.startswith("/"):
        text = text[1:]
    if (
        not text
        or text.startswith("/")
        or "\\" in text
        or ".." in text
        or "://" in text
        or "\x00" in text
    ):
        return None
    parts = text.split("/")
    if len(parts) != 2:
        return None
    folder, name = parts
    if folder not in _FOLDERS or not _OBJECT_NAME.fullmatch(name):
        return None
    return f"{folder}/{name}"


def _s3() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url.strip(),
        aws_access_key_id=settings.s3_access_key_id.get_secret_value().strip(),
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value().strip(),
        # Cloudflare R2 expects this region name.
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _put_object(key: str, data: bytes, content_type: str) -> None:
    try:
        _s3().put_object(
            Bucket=settings.s3_bucket.strip(),
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl=_CACHE_CONTROL,
        )
    except (BotoCoreError, ClientError) as exc:
        _log_storage_failure("media_upload_failed", key, exc)
        raise RuntimeError("Could not store the uploaded file") from exc


def _delete_object(key: str) -> None:
    try:
        _s3().delete_object(Bucket=settings.s3_bucket.strip(), Key=key)
    except (BotoCoreError, ClientError) as exc:
        _log_storage_failure("media_delete_failed", key, exc)
        raise RuntimeError("Could not delete the uploaded file") from exc


def _log_storage_failure(event: str, key: str, exc: Exception) -> None:
    code = ""
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
    # The key is a generated filename. The error code is enough to look up
    # the failure; the message can echo request details, so it stays out.
    logger.error(event, key=key, error_code=code)


def real_uploads(files: list[UploadFile] | None) -> list[UploadFile]:
    if not files:
        return []
    kept = [item for item in files if item.filename]
    if len(kept) > _MAX_FILES:
        raise UnprocessableError("A product can have at most 12 images")
    return kept


def owned_refs(*refs: str, folder: str = "products") -> set[str]:
    prefix = f"/media/{_folder(folder)}/"
    return {ref for ref in refs if ref.startswith(prefix)}
