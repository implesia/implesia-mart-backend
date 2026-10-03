import uuid

from pydantic import BaseModel, Field, field_validator


def _href(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "/products?view=featured"
    if not (
        cleaned.startswith("/")
        or cleaned.startswith("http://")
        or cleaned.startswith("https://")
    ):
        raise ValueError("href must start with / or http")
    return cleaned


class FeaturedProductCard(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    price: int
    image_src: str
    published: bool


class FeaturedItemRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sort_order: int
    product: FeaturedProductCard | None


class FeaturedAdmin(BaseModel):
    heading: str
    view_all_label: str
    view_all_href: str
    items: list[FeaturedItemRead]
    choices: list[FeaturedProductCard]


class FeaturedPublic(BaseModel):
    heading: str
    view_all_label: str
    view_all_href: str
    product_ids: list[uuid.UUID]


class FeaturedCopyUpdate(BaseModel):
    heading: str = Field(max_length=120)
    view_all_label: str = Field(max_length=80)
    view_all_href: str = Field("", max_length=255)

    @field_validator("heading", "view_all_label")
    @classmethod
    def _text(cls, value: str) -> str:
        return value.strip()

    @field_validator("view_all_href")
    @classmethod
    def _check_href(cls, value: str) -> str:
        return _href(value)


class FeaturedItemWrite(BaseModel):
    product_id: uuid.UUID


class FeaturedReorder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=12)
