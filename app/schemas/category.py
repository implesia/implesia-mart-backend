import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import WriteModel

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_SLUG = re.compile(SLUG_PATTERN)
RESERVED_SLUGS = frozenset({"tree", "order"})
_CONTROL = dict.fromkeys(range(32))


def _line(value: str, label: str) -> str:
    cleaned = " ".join(value.translate(_CONTROL).split())
    if not cleaned:
        raise ValueError(f"{label} is required")
    return cleaned


def _media(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if any(ch.isspace() for ch in cleaned) or "\\" in cleaned or ".." in cleaned.split("/"):
        raise ValueError("Image address is not allowed")
    if not (cleaned.startswith(("/", "https://", "http://"))):
        raise ValueError("Image address must start with / or http")
    if cleaned.lower().startswith(("javascript:", "data:", "vbscript:", "file:", "blob:")):
        raise ValueError("Image address is not allowed")
    return cleaned


def _slug(value: str) -> str:
    cleaned = value.strip().lower()
    if not _SLUG.fullmatch(cleaned):
        raise ValueError("Use lowercase letters, numbers, and single hyphens")
    if cleaned in RESERVED_SLUGS:
        raise ValueError("This address is reserved")
    return cleaned


class CategoryRef(BaseModel):
    """Minimal pointer used in breadcrumbs and product cards."""

    id: uuid.UUID
    slug: str
    name: str


class CategoryWrite(WriteModel):
    parent_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    # Empty slug: generated from the name (ASCII) or from a safe fallback.
    slug: str = Field("", max_length=80)
    description: str = Field("", max_length=2000)
    image_src: str = Field("", max_length=255)
    is_active: bool = True
    meta_title: str = Field("", max_length=160)
    meta_description: str = Field("", max_length=320)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _line(value, "Name")

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str) -> str:
        return _slug(value) if value.strip() else ""

    @field_validator("image_src")
    @classmethod
    def _image(cls, value: str) -> str:
        return _media(value)

    @field_validator("description", "meta_title", "meta_description")
    @classmethod
    def _text(cls, value: str) -> str:
        return value.replace("\x00", "").strip()


class CategoryUpdate(WriteModel):
    # parent_id: omit to keep the parent, send null to move to the top level.
    parent_id: uuid.UUID | None = None
    name: str | None = Field(None, min_length=1, max_length=120)
    slug: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = Field(None, max_length=2000)
    image_src: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    meta_title: str | None = Field(None, max_length=160)
    meta_description: str | None = Field(None, max_length=320)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _line(value, "Name")

    @field_validator("slug")
    @classmethod
    def _check_slug(cls, value: str | None) -> str | None:
        return None if value is None else _slug(value)

    @field_validator("image_src")
    @classmethod
    def _image(cls, value: str | None) -> str | None:
        return None if value is None else _media(value)

    @field_validator("description", "meta_title", "meta_description")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        return None if value is None else value.replace("\x00", "").strip()


class CategoryOrder(WriteModel):
    """Reorder the children of one parent (null = the top level)."""

    parent_id: uuid.UUID | None = None
    ids: list[uuid.UUID] = Field(max_length=500)


class CategoryAdminRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None
    slug: str
    name: str
    description: str
    image_src: str
    is_active: bool
    sort_order: int
    meta_title: str
    meta_description: str
    created_at: datetime
    updated_at: datetime
    depth: int = 1
    child_count: int = 0
    # Products assigned directly to this node / to it or any descendant (all states).
    product_count: int = 0
    subtree_product_count: int = 0
    # False when this node or an ancestor is inactive: the storefront hides it.
    visible: bool = True
    path: list[CategoryRef] = Field(default_factory=list)


class CategoryAdminList(BaseModel):
    items: list[CategoryAdminRead]
    max_depth: int


class CategoryNode(BaseModel):
    """Public tree node. `product_count` covers published products in the subtree."""

    id: uuid.UUID
    slug: str
    name: str
    description: str
    image_src: str
    depth: int
    product_count: int
    children: list["CategoryNode"] = Field(default_factory=list)


class CategoryTree(BaseModel):
    items: list[CategoryNode]


class CategoryDetail(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    image_src: str
    meta_title: str
    meta_description: str
    depth: int
    product_count: int
    path: list[CategoryRef]
    children: list[CategoryNode]
