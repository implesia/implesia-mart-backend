import re

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.common import WriteModel

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ICON = re.compile(r"^[a-z0-9_]{1,40}$")
_PHONE = re.compile(r"^[0-9+\-().]{3,30}$")


def clean(value: object) -> object:
    if isinstance(value, str):
        return _CONTROL.sub("", value).strip()
    return value


def no_html(value: str) -> str:
    if "<" in value or ">" in value:
        raise ValueError("HTML is not allowed here; use plain text")
    return value


def link_ref_ok(value: str) -> bool:
    """A footer link target: site path, http(s), mailto: or tel:. Nothing else (no
    javascript:, data:, blob:, file:, protocol-relative or whitespace/control characters)."""
    if not value:
        return False
    if len(value) > 255 or any(ch.isspace() or ord(ch) < 32 for ch in value):
        return False
    lowered = value.lower()
    if lowered.startswith("mailto:"):
        address = value[7:].split("?", 1)[0]
        return bool(re.fullmatch(r"[^@/\\:,;]+@[^@/\\:,;]+\.[^@/\\:,;]+", address))
    if lowered.startswith("tel:"):
        return bool(_PHONE.fullmatch(value[4:]))
    if value.startswith("/") or lowered.startswith(("http://", "https://")):
        return cover_ref_ok(value)
    return False


_REF_MESSAGE = "Use a site path starting with /, an http(s) link, mailto: or tel:"


class FooterLink(WriteModel):
    label: str = Field(min_length=1, max_length=80)
    href: str = Field(min_length=1, max_length=255)
    enabled: bool = True

    _clean = field_validator("label", "href", mode="before")(clean)
    _plain = field_validator("label")(no_html)

    @field_validator("href")
    @classmethod
    def _href(cls, value: str) -> str:
        if not link_ref_ok(value):
            raise ValueError(_REF_MESSAGE)
        return value


class FooterSection(WriteModel):
    title: str = Field(min_length=1, max_length=60)
    enabled: bool = True
    links: list[FooterLink] = Field(default_factory=list, max_length=12)

    _clean = field_validator("title", mode="before")(clean)
    _plain = field_validator("title")(no_html)


class TrustPoint(WriteModel):
    icon: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    enabled: bool = True

    _clean = field_validator("icon", "label", mode="before")(clean)
    _plain = field_validator("label")(no_html)

    @field_validator("icon")
    @classmethod
    def _icon(cls, value: str) -> str:
        if not _ICON.fullmatch(value):
            raise ValueError("Icon names use lowercase letters, digits and underscores")
        return value


class FooterWrite(WriteModel):
    brand_name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=400)
    logo_src: str = Field("", max_length=255)
    logo_alt: str = Field("", max_length=120)
    address: str = Field("", max_length=300)
    copyright_text: str = Field(min_length=1, max_length=160)
    show_contact: bool = True
    show_social: bool = True
    show_whatsapp_cta: bool = True
    sections: list[FooterSection] = Field(default_factory=list, max_length=8)
    trust_points: list[TrustPoint] = Field(default_factory=list, max_length=6)
    legal_links: list[FooterLink] = Field(default_factory=list, max_length=8)

    _clean = field_validator(
        "brand_name",
        "description",
        "logo_src",
        "logo_alt",
        "address",
        "copyright_text",
        mode="before",
    )(clean)
    _plain = field_validator("brand_name", "description", "logo_alt", "address", "copyright_text")(
        no_html
    )

    @field_validator("logo_src")
    @classmethod
    def _logo(cls, value: str) -> str:
        if not cover_ref_ok(value):
            raise ValueError("Use a site path starting with / or an http(s) link")
        return value

    @model_validator(mode="after")
    def _complete(self) -> "FooterWrite":
        if self.logo_src and not self.logo_alt:
            raise ValueError("Describe the logo for screen readers")
        return self


class FooterPublic(BaseModel):
    """What the storefront renders: only enabled sections/links, each already validated."""

    brand_name: str
    description: str
    logo_src: str
    logo_alt: str
    address: str
    copyright_text: str
    show_contact: bool
    show_social: bool
    show_whatsapp_cta: bool
    sections: list[FooterSection]
    trust_points: list[TrustPoint]
    legal_links: list[FooterLink]


class FooterAdmin(FooterPublic):
    """Everything an editor can change, including disabled items."""

    is_default: bool = False
    logo_needs_upload: bool = False


class ImageUploaded(BaseModel):
    url: str
