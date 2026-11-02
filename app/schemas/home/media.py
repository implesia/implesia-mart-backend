import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.common import WriteModel
from app.schemas.product import VIDEO_SUFFIXES, youtube_id

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MediaType = Literal["image", "video", "youtube"]


def _clean(value: object) -> object:
    if isinstance(value, str):
        return _CONTROL.sub("", value).strip()
    return value


def cta_href_ok(value: str) -> bool:
    """A site path ("/products") or an https link. Nothing else is a button target."""
    if not value:
        return True
    if len(value) > 255 or any(ch.isspace() or ord(ch) < 32 for ch in value) or "\\" in value:
        return False
    if value.startswith("/"):
        return not value.startswith("//") and ".." not in value
    parts = urlsplit(value)
    return parts.scheme == "https" and bool(parts.hostname)


def video_ref_ok(value: str) -> bool:
    """An uploaded MP4/WEBM path or link (query strings aside)."""
    if not value:
        return True
    return cover_ref_ok(value) and urlsplit(value).path.lower().endswith(VIDEO_SUFFIXES)


class MediaPublic(BaseModel):
    """What the storefront renders. Only returned while the section is live and complete."""

    heading: str
    subheading: str
    media_type: MediaType
    image_src: str
    video_src: str
    youtube_id: str
    thumbnail_src: str
    media_alt: str
    description: str
    cta_label: str
    cta_href: str


class MediaAdmin(MediaPublic):
    is_active: bool
    cta_enabled: bool
    # The watch link for the stored YouTube id ("" when none), for the editor's input.
    youtube_url: str
    # True when a stored file can no longer be shown (not a usable path or URL).
    media_needs_upload: bool = False


class MediaWrite(WriteModel):
    is_active: bool = False
    heading: str = Field("", max_length=120)
    subheading: str = Field("", max_length=240)
    media_type: MediaType = "image"
    image_src: str = Field("", max_length=255)
    video_src: str = Field("", max_length=255)
    # A YouTube watch / youtu.be / shorts / embed link or a bare id; stored as the id.
    youtube_url: str = Field("", max_length=300)
    thumbnail_src: str = Field("", max_length=255)
    media_alt: str = Field("", max_length=200)
    description: str = Field("", max_length=500)
    cta_enabled: bool = False
    cta_label: str = Field("", max_length=60)
    cta_href: str = Field("", max_length=255)

    _strip = field_validator(
        "heading",
        "subheading",
        "image_src",
        "video_src",
        "youtube_url",
        "thumbnail_src",
        "media_alt",
        "description",
        "cta_label",
        "cta_href",
        mode="before",
    )(_clean)

    @field_validator("image_src", "thumbnail_src")
    @classmethod
    def _image(cls, value: str) -> str:
        if not cover_ref_ok(value):
            raise ValueError("Use a site path starting with / or an http(s) link")
        return value

    @field_validator("video_src")
    @classmethod
    def _video(cls, value: str) -> str:
        if not video_ref_ok(value):
            raise ValueError("Upload an MP4 or WEBM video")
        return value

    @field_validator("youtube_url")
    @classmethod
    def _youtube(cls, value: str) -> str:
        return youtube_id(value) if value else ""

    @field_validator("cta_href")
    @classmethod
    def _cta(cls, value: str) -> str:
        if not cta_href_ok(value):
            raise ValueError("Button link must start with / or https://")
        return value

    @model_validator(mode="after")
    def _complete(self) -> "MediaWrite":
        if self.cta_enabled and not (self.cta_label and self.cta_href):
            raise ValueError("Give the button both a label and a link, or turn it off")
        if self.is_active:
            if not self.heading:
                raise ValueError("Add a heading before publishing")
            if self.media_type == "image" and not self.image_src:
                raise ValueError("Add an image before publishing")
            if self.media_type == "image" and not self.media_alt:
                raise ValueError("Describe the image for screen readers before publishing")
            if self.media_type == "video" and not self.video_src:
                raise ValueError("Upload a video before publishing")
            if self.media_type == "youtube" and not self.youtube_url:
                raise ValueError("Add a YouTube link before publishing")
        return self


class MediaUploaded(BaseModel):
    url: str
