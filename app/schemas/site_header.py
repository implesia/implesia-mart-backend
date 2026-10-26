from pydantic import BaseModel, Field, model_validator

from app.schemas.common import WriteModel
from app.schemas.site_footer import FooterLink

MAX_ITEMS = 8


class HeaderWrite(WriteModel):
    """The whole menu, in display order. Link rules are the footer's (site path, http(s),
    mailto: or tel:; no javascript:, data: or protocol-relative targets)."""

    items: list[FooterLink] = Field(min_length=1, max_length=MAX_ITEMS)

    @model_validator(mode="after")
    def _something_shown(self) -> "HeaderWrite":
        if not any(item.enabled for item in self.items):
            raise ValueError("Keep at least one menu link shown")
        return self


class HeaderPublic(BaseModel):
    """What the storefront renders: only enabled links, each already validated."""

    items: list[FooterLink]


class HeaderAdmin(HeaderPublic):
    """Every link an editor can change, including hidden ones."""

    is_default: bool = False
