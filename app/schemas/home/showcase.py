import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel
from app.schemas.home.featured import FeaturedProductCard


def _href(value: str, fallback: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return fallback
    if not (
        cleaned.startswith("/")
        or cleaned.startswith("http://")
        or cleaned.startswith("https://")
    ):
        raise ValueError("href must start with / or http")
    return cleaned


class ShowcaseItemRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sort_order: int
    product: FeaturedProductCard | None


class ShowcaseRowAdmin(BaseModel):
    id: uuid.UUID
    key: str
    heading: str
    href: str
    items: list[ShowcaseItemRead]
    choices: list[FeaturedProductCard]


class ShowcaseAdmin(BaseModel):
    rows: list[ShowcaseRowAdmin]


class ShowcaseRowPublic(BaseModel):
    key: str
    heading: str
    href: str
    product_ids: list[uuid.UUID]


class ShowcasePublic(BaseModel):
    rows: list[ShowcaseRowPublic]


class ShowcaseRowUpdate(WriteModel):
    heading: str = Field(max_length=120)
    href: str = Field("", max_length=255)

    @field_validator("heading")
    @classmethod
    def _heading(cls, value: str) -> str:
        return value.strip()


class ShowcaseItemWrite(WriteModel):
    product_id: uuid.UUID


class ShowcaseReorder(WriteModel):
    ids: list[uuid.UUID] = Field(max_length=12)


def clean_href(value: str, fallback: str) -> str:
    return _href(value, fallback)
