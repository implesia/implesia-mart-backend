"""Store product images outside the application code.

Bytes are identified by signature, not by the client-supplied type. The stored
name is generated. SVG, HTML, and any other executable content are rejected.
"""

import uuid

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import UnprocessableError

_MAX_FILES = 12
_READ = 64 * 1024
_OWNED_PREFIX = "/media/products/"

# (signature, suffix). WebP is checked separately because the mark is not a prefix.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


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


def store_image(data: bytes) -> str:
    suffix = sniff_image(data)
    directory = (settings.media_root / "products").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{suffix}"
    path = directory / name
    path.write_bytes(data)
    return f"{_OWNED_PREFIX}{name}"


def delete_owned_media(refs: set[str]) -> None:
    root = (settings.media_root / "products").resolve()
    for ref in refs:
        if not ref.startswith(_OWNED_PREFIX):
            continue
        name = ref.removeprefix(_OWNED_PREFIX)
        if not name or "/" in name or "\\" in name or name.startswith("."):
            continue
        path = (root / name).resolve()
        if path.parent != root:
            continue
        path.unlink(missing_ok=True)


def real_uploads(files: list[UploadFile] | None) -> list[UploadFile]:
    if not files:
        return []
    kept = [item for item in files if item.filename]
    if len(kept) > _MAX_FILES:
        raise UnprocessableError("A product can have at most 12 images")
    return kept


def owned_refs(*refs: str) -> set[str]:
    return {ref for ref in refs if ref.startswith(_OWNED_PREFIX)}
