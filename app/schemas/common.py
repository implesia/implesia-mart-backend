from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

_SCRIPT_SCHEMES = ("javascript:", "data:", "vbscript:", "file:", "blob:")


def page_count(total: int, page_size: int) -> int:
    if page_size <= 0:
        return 0
    return (total + page_size - 1) // page_size


class PaginationParams(BaseModel):
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class Message(BaseModel):
    message: str


class WriteModel(BaseModel):
    """Admin request body. A field the schema does not declare is rejected."""

    model_config = ConfigDict(extra="forbid")

    # Set True on a schema whose service already runs `_safe_href` and answers with a
    # section-specific message ("Link is not allowed"); the generic guard then stands aside
    # so that message is not replaced by a generic 422.
    href_checked_by_service: ClassVar[bool] = False

    @field_validator("*", mode="after")
    @classmethod
    def _no_script_href(cls, value: object, info: ValidationInfo) -> object:
        """Any admin-writable `href` / `*_href` field refuses script-capable schemes.

        Storefront links are rendered as `<a href>`, so `javascript:` (also with spaces,
        tabs or control characters inside the scheme, which browsers ignore) would run in a
        visitor's browser. Field-specific rules (footer links, contact channels, hero
        buttons) are stricter and run in addition.
        """
        name = info.field_name or ""
        if cls.href_checked_by_service:
            return value
        if (name == "href" or name.endswith("_href")) and isinstance(value, str):
            compact = "".join(ch for ch in value if ord(ch) > 32 and ord(ch) != 127).lower()
            if compact.startswith(_SCRIPT_SCHEMES):
                raise ValueError("This link scheme is not allowed")
        return value
