import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _href(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "/products"
    if not (
        cleaned.startswith("/")
        or cleaned.startswith("http://")
        or cleaned.startswith("https://")
    ):
        raise ValueError("href must start with / or http")
    return cleaned


class CategoryTileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    href: str
    image_src: str
    is_active: bool
    sort_order: int


class CategoryTilePublic(BaseModel):
    id: uuid.UUID
    label: str
    href: str
    image_src: str


class CategoryAdmin(BaseModel):
    heading: str
    tiles: list[CategoryTileRead]


class CategoryPublic(BaseModel):
    heading: str
    tiles: list[CategoryTilePublic]


class CategoryHeadingUpdate(BaseModel):
    heading: str = Field(max_length=120)

    @field_validator("heading")
    @classmethod
    def _heading(cls, value: str) -> str:
        return value.strip()


class CategoryTileWrite(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    href: str = Field("", max_length=255)
    image_src: str = Field("", max_length=255)
    is_active: bool = True

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Label is required")
        return cleaned

    @field_validator("href")
    @classmethod
    def _check_href(cls, value: str) -> str:
        return _href(value)


class CategoryTileUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=120)
    href: str | None = Field(None, max_length=255)
    image_src: str | None = Field(None, max_length=255)
    is_active: bool | None = None

    @field_validator("label")
    @classmethod
    def _label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Label is required")
        return cleaned

    @field_validator("href")
    @classmethod
    def _check_href(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _href(value)


class CategoryReorder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=24)
