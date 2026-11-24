from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.blogs.posts import cover_ref_ok
from app.schemas.common import WriteModel
from app.schemas.site_footer import FooterLink, clean, no_html

MAX_ITEMS = 8


class HeaderWrite(WriteModel):
    """The whole menu, in display order, plus the optional navbar logo. Link rules are the
    footer's (site path, http(s), mailto: or tel:; no javascript:, data: or protocol-relative
    targets)."""

    items: list[FooterLink] = Field(min_length=1, max_length=MAX_ITEMS)
    logo_src: str = Field("", max_length=255)
    logo_alt: str = Field("", max_length=120)

    _clean = field_validator("logo_src", "logo_alt", mode="before")(clean)
    _plain = field_validator("logo_alt")(no_html)

    @field_validator("logo_src")
    @classmethod
    def _logo(cls, value: str) -> str:
        if not cover_ref_ok(value):
            raise ValueError("Use a site path starting with / or an http(s) link")
        return value

    @model_validator(mode="after")
    def _something_shown(self) -> "HeaderWrite":
        if not any(item.enabled for item in self.items):
            raise ValueError("Keep at least one menu link shown")
        if self.logo_src and not self.logo_alt:
            raise ValueError("Describe the logo for screen readers")
        return self


class HeaderPublic(BaseModel):
    """What the storefront renders: only enabled links, each already validated."""

    items: list[FooterLink]
    logo_src: str = ""
    logo_alt: str = ""


class HeaderAdmin(HeaderPublic):
    """Every link an editor can change, including hidden ones."""

    is_default: bool = False
    logo_needs_upload: bool = False
