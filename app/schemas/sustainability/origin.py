import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class OriginImagePublic(BaseModel):
    id: uuid.UUID
    src: str
    alt: str


class OriginImageAdmin(OriginImagePublic):
    is_active: bool


class OriginPublic(BaseModel):
    eyebrow: str
    title: str
    body: str
    quote: str
    images: list[OriginImagePublic]


class OriginAdmin(BaseModel):
    eyebrow: str
    title: str
    body: str
    quote: str
    images: list[OriginImageAdmin]


class OriginImageWrite(WriteModel):
    alt: str = Field(default="", max_length=200)
    src: str = Field(default="", max_length=255)
    is_active: bool = True

    @field_validator("alt", "src", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class OriginWrite(WriteModel):
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=800)
    quote: str = Field(default="", max_length=400)
    images: list[OriginImageWrite] = Field(default_factory=list, max_length=12)

    @field_validator("eyebrow", "title", "body", "quote", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
