import re

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.common import WriteModel

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(value: object) -> object:
    if isinstance(value, str):
        return _CONTROL.sub("", value).strip()
    return value


class PopupPublic(BaseModel):
    """Storefront popup payload. Only returned when active and has content."""

    badge_text: str
    heading: str
    body: str
    coupon_code: str
    cta_label: str
    cta_href: str
    image_src: str
    image_alt: str
    delay_seconds: int
    min_scroll_px: int
    dismiss_cooldown_hours: int
    show_on_all_pages: bool
    version: str


class PopupAdmin(BaseModel):
    is_active: bool
    badge_text: str
    heading: str
    body: str
    coupon_code: str
    cta_label: str
    cta_href: str
    image_src: str
    image_alt: str
    delay_seconds: int
    min_scroll_px: int
    dismiss_cooldown_hours: int
    show_on_all_pages: bool
    image_needs_upload: bool = False


class PopupWrite(WriteModel):
    is_active: bool = False
    badge_text: str = Field("", max_length=60)
    heading: str = Field("", max_length=140)
    body: str = Field("", max_length=400)
    coupon_code: str = Field("", max_length=40)
    cta_label: str = Field("", max_length=60)
    cta_href: str = Field("", max_length=255)
    image_src: str = Field("", max_length=255)
    image_alt: str = Field("", max_length=200)
    delay_seconds: int = Field(4, ge=0, le=60)
    min_scroll_px: int = Field(150, ge=0, le=2000)
    dismiss_cooldown_hours: int = Field(24, ge=0, le=720)
    show_on_all_pages: bool = True

    _strip = field_validator(
        "badge_text",
        "heading",
        "body",
        "coupon_code",
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
    def _complete(self) -> "PopupWrite":
        if bool(self.cta_label) != bool(self.cta_href):
            raise ValueError("Give the CTA button both a label and a link, or neither")
        if self.is_active and not (self.heading or self.image_src):
            raise ValueError("Add a heading or a popup image before enabling the popup")
        return self


class PopupImageUploaded(BaseModel):
    url: str
