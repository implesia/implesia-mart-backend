import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.about.single_image import SingleImageMixin, SingleImageWrite
from app.schemas.common import WriteModel


def _href(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if not (
        cleaned.startswith("/") or cleaned.startswith("http://") or cleaned.startswith("https://")
    ):
        raise ValueError("href must start with / or http")
    return cleaned


class DressFeatureRead(BaseModel):
    id: uuid.UUID
    icon: str
    title: str
    description: str


class DressImageRead(BaseModel):
    id: uuid.UUID
    src: str
    alt: str


class DressRead(BaseModel):
    id: uuid.UUID
    kicker: str
    title: str
    subtitle: str
    features: list[DressFeatureRead]
    primary_label: str
    primary_href: str
    secondary_label: str
    secondary_href: str
    is_active: bool
    image: DressImageRead | None = None
    # Deprecated mirror of `image` (0 or 1 item).
    images: list[DressImageRead]


class DressPublic(BaseModel):
    id: uuid.UUID
    kicker: str
    title: str
    subtitle: str
    features: list[DressFeatureRead]
    primary_label: str
    primary_href: str
    secondary_label: str
    secondary_href: str
    image: DressImageRead | None = None
    # Deprecated mirror of `image` (0 or 1 item).
    images: list[DressImageRead]


class DressesPublic(BaseModel):
    items: list[DressPublic]


class DressFeatureWrite(WriteModel):
    icon: str = Field(default="design_services", max_length=40)
    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=300)

    @field_validator("icon", "title", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("icon")
    @classmethod
    def _icon(cls, value: str) -> str:
        return value or "design_services"


DressImageWrite = SingleImageWrite


class DressWrite(SingleImageMixin):
    kicker: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=800)
    features: list[DressFeatureWrite] = Field(default_factory=list)
    primary_label: str = Field(default="", max_length=80)
    primary_href: str = Field(default="", max_length=800)
    secondary_label: str = Field(default="", max_length=80)
    secondary_href: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("kicker", "title", "subtitle", "primary_label", "secondary_label")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("primary_href", "secondary_href")
    @classmethod
    def _check_href(cls, value: str) -> str:
        return _href(value)

    @field_validator("features")
    @classmethod
    def _drop_empty(cls, value: list[DressFeatureWrite]) -> list[DressFeatureWrite]:
        return [item for item in value if item.title or item.description]


class DressReorder(WriteModel):
    ids: list[uuid.UUID] = Field(max_length=12)
