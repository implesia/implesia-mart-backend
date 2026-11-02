"""The home page media section (image, uploaded video or YouTube) above the testimonials."""

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnprocessableError
from app.models.home.media import HomeMedia
from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.home.media import MediaAdmin, MediaPublic, MediaWrite, video_ref_ok
from app.services.image_storage import (
    delete_owned_media,
    read_image,
    read_video,
    store_image,
    store_video,
)

MEDIA_SLUG = "home"
_FOLDER = "home-media"
_PREFIX = f"/media/{_FOLDER}/"
_FILE_FIELDS = ("image_src", "video_src", "thumbnail_src")


async def _row(db: AsyncSession) -> HomeMedia | None:
    return await db.scalar(select(HomeMedia).where(HomeMedia.slug == MEDIA_SLUG))


def _image(value: str) -> str:
    """A stored image the storefront can use, or "" for an unusable one."""
    return value if cover_ref_ok(value) else ""


def _video(value: str) -> str:
    return value if video_ref_ok(value) else ""


def _media_type(value: str) -> str:
    return value if value in {"image", "video", "youtube"} else "image"


def _fields(row: HomeMedia) -> dict[str, str]:
    kind = _media_type(row.media_type)
    href = row.cta_href if row.cta_enabled and row.cta_label else ""
    return {
        "heading": row.heading,
        "subheading": row.subheading,
        "media_type": kind,
        "image_src": _image(row.image_src) if kind == "image" else "",
        "video_src": _video(row.video_src) if kind == "video" else "",
        "youtube_id": row.youtube_id if kind == "youtube" else "",
        "thumbnail_src": _image(row.thumbnail_src) if kind != "image" else "",
        "media_alt": row.media_alt,
        "description": row.description,
        "cta_label": row.cta_label if href else "",
        "cta_href": href,
    }


async def public_view(db: AsyncSession) -> MediaPublic | None:
    """The live section, or None: no row, hidden, or no usable media all show nothing."""
    row = await _row(db)
    if row is None or not row.is_active:
        return None
    fields = _fields(row)
    kind = fields["media_type"]
    if kind == "image" and not (fields["image_src"] and fields["media_alt"]):
        return None
    if kind == "video" and not fields["video_src"]:
        return None
    if kind == "youtube" and not fields["youtube_id"]:
        return None
    return MediaPublic.model_validate(fields)


async def admin_view(db: AsyncSession) -> MediaAdmin:
    row = await _row(db)
    if row is None:
        return MediaAdmin(
            is_active=False,
            heading="",
            subheading="",
            media_type="image",
            image_src="",
            video_src="",
            youtube_id="",
            thumbnail_src="",
            media_alt="",
            description="",
            cta_enabled=False,
            cta_label="",
            cta_href="",
            youtube_url="",
        )
    fields = _fields(row)
    stored = {name: getattr(row, name) for name in _FILE_FIELDS}
    lost = any(
        value and not _image(value) for value in (stored["image_src"], stored["thumbnail_src"])
    )
    lost = lost or bool(stored["video_src"] and not _video(stored["video_src"]))
    return MediaAdmin.model_validate(
        {
            **fields,
            # The editor keeps its own button text and link even while the button is off.
            "cta_label": row.cta_label,
            "cta_href": row.cta_href,
            "is_active": row.is_active,
            "cta_enabled": row.cta_enabled,
            "youtube_url": (
                f"https://www.youtube.com/watch?v={fields['youtube_id']}"
                if fields["youtube_id"]
                else ""
            ),
            "media_needs_upload": lost,
        }
    )


async def update(db: AsyncSession, payload: MediaWrite) -> MediaAdmin:
    row = await _row(db)
    if row is None:
        row = HomeMedia(slug=MEDIA_SLUG)
        db.add(row)
        previous: set[str] = set()
    else:
        previous = {getattr(row, name) for name in _FILE_FIELDS}
    data = payload.model_dump()
    data["youtube_id"] = data.pop("youtube_url")
    # Only the chosen media type is kept, so a replaced video or image does not linger.
    kind = payload.media_type
    if kind != "image":
        data["image_src"] = ""
    if kind != "video":
        data["video_src"] = ""
    if kind != "youtube":
        data["youtube_id"] = ""
    if kind == "image":
        data["thumbnail_src"] = ""
    for field, value in data.items():
        setattr(row, field, value)
    await db.commit()
    kept = {data[name] for name in _FILE_FIELDS}
    stale = {ref for ref in previous - kept if ref.startswith(_PREFIX) and cover_ref_ok(ref)}
    if stale:
        delete_owned_media(stale, folder=_FOLDER)
    return await admin_view(db)


async def upload_image(upload: UploadFile) -> str:
    """Validate (type by bytes, size) and store one image or thumbnail."""
    if not upload.filename:
        raise UnprocessableError("Choose an image file.")
    return store_image(await read_image(upload), folder=_FOLDER)


async def upload_video(upload: UploadFile) -> str:
    """Validate (MP4/WEBM by bytes, up to the 50 MB video limit) and store one video."""
    if not upload.filename:
        raise UnprocessableError("Choose a video file.")
    return store_video(await read_video(upload), folder=_FOLDER)
