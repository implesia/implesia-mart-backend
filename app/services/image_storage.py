"""Store uploaded images on this instance's disk, under `/media`.

Workers in one container share that directory. A second API instance behind a
load balancer would not. Move these files to object storage before adding one.
Bytes are identified by signature, not by the client-supplied type. The stored
name is generated. SVG, HTML, and any other executable content are rejected.
"""

import uuid

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import UnprocessableError

_MAX_FILES = 12
_READ = 64 * 1024
_FOLDERS = frozenset({"products", "banners", "categories", "reviews", "about", "sustainability"})

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


def _folder(name: str) -> str:
    if name not in _FOLDERS:
        raise ValueError(f"Unknown media folder: {name}")
    return name


def store_image(data: bytes, *, folder: str = "products") -> str:
    folder = _folder(folder)
    suffix = sniff_image(data)
    directory = (settings.media_root / folder).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{suffix}"
    path = directory / name
    path.write_bytes(data)
    return f"/media/{folder}/{name}"


def delete_owned_media(refs: set[str], *, folder: str = "products") -> None:
    folder = _folder(folder)
    prefix = f"/media/{folder}/"
    root = (settings.media_root / folder).resolve()
    for ref in refs:
        if not ref.startswith(prefix):
            continue
        name = ref.removeprefix(prefix)
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


def owned_refs(*refs: str, folder: str = "products") -> set[str]:
    prefix = f"/media/{_folder(folder)}/"
    return {ref for ref in refs if ref.startswith(prefix)}
