import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.common import WriteModel

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
Tone = Literal["dark", "light"]


def _clean(value: object) -> object:
    if isinstance(value, str):
        return _CONTROL.sub("", value).strip()
    return value


class PromoPublic(BaseModel):
    """What the storefront renders. Only returned while the banner is live and complete."""

    eyebrow: str
    heading: str
    body: str
    cta_label: str
    cta_href: str
    image_src: str
    image_alt: str
    focal_x: int
    focal_y: int
    tone: Tone


class PromoAdmin(BaseModel):
    is_active: bool
    eyebrow: str
    heading: str
    body: str
    cta_label: str
    cta_href: str
    image_src: str
    image_alt: str
    focal_x: int
    focal_y: int
    tone: Tone
    # True when a stored image can no longer be shown (not a usable path or URL).
    image_needs_upload: bool = False


class PromoWrite(WriteModel):
    is_active: bool = False
    eyebrow: str = Field("", max_length=80)
    heading: str = Field("", max_length=120)
    body: str = Field("", max_length=200)
    cta_label: str = Field("", max_length=60)
    cta_href: str = Field("", max_length=255)
    image_src: str = Field("", max_length=255)
    image_alt: str = Field("", max_length=200)
    focal_x: int = Field(50, ge=0, le=100)
    focal_y: int = Field(50, ge=0, le=100)
    tone: Tone = "dark"

    _strip = field_validator(
        "eyebrow",
        "heading",
        "body",
        "cta_label",
        "cta_href",
        "image_src",
        "image_alt",
        mode="before",
    )(_clean)

    @field_validator("image_src", "cta_href")
    @classmethod
    def _ref(cls, value: str) -> str:
        if not cover_ref_ok(value):
            raise ValueError("Use a site path starting with / or an http(s) link")
        return value

    @model_validator(mode="after")
    def _complete(self) -> "PromoWrite":
        if bool(self.cta_label) != bool(self.cta_href):
            raise ValueError("Give the button both a label and a link, or neither")
        if self.is_active:
            if not self.image_src:
                raise ValueError("Add a banner image before publishing")
            if not self.image_alt:
                raise ValueError("Describe the image for screen readers before publishing")
        return self


class ImageUploaded(BaseModel):
    url: str
