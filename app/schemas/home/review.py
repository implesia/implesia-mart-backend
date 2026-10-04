import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import WriteModel

ReviewChannel = Literal["WhatsApp", "Messenger"]


class ReviewItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product: str
    channel: ReviewChannel
    image_src: str
    image_alt: str
    is_active: bool
    sort_order: int


class ReviewItemPublic(BaseModel):
    id: uuid.UUID
    product: str
    channel: ReviewChannel
    image_src: str
    image_alt: str


class ReviewAdmin(BaseModel):
    kicker: str
    title: str
    subtitle: str
    items: list[ReviewItemRead]


class ReviewPublic(BaseModel):
    kicker: str
    title: str
    subtitle: str
    items: list[ReviewItemPublic]


class ReviewCopyUpdate(WriteModel):
    kicker: str = Field(max_length=80)
    title: str = Field(max_length=160)
    subtitle: str = Field(max_length=400)

    @field_validator("kicker", "title", "subtitle")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class ReviewItemWrite(WriteModel):
    product: str = Field(min_length=1, max_length=120)
    channel: ReviewChannel = "WhatsApp"
    image_src: str = Field("", max_length=255)
    image_alt: str = Field("", max_length=255)
    is_active: bool = True

    @field_validator("product")
    @classmethod
    def _product(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Product is required")
        return cleaned

    @field_validator("image_alt")
    @classmethod
    def _alt(cls, value: str) -> str:
        return value.strip()


class ReviewItemUpdate(WriteModel):
    product: str | None = Field(None, min_length=1, max_length=120)
    channel: ReviewChannel | None = None
    image_src: str | None = Field(None, max_length=255)
    image_alt: str | None = Field(None, max_length=255)
    is_active: bool | None = None

    @field_validator("product")
    @classmethod
    def _product(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Product is required")
        return cleaned

    @field_validator("image_alt")
    @classmethod
    def _alt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class ReviewReorder(WriteModel):
    ids: list[uuid.UUID] = Field(max_length=24)
