import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class DurabilityImageRead(BaseModel):
    src: str
    alt: str


class DurabilityBulletPublic(BaseModel):
    id: uuid.UUID
    text: str


class DurabilityBulletRead(DurabilityBulletPublic):
    is_active: bool


class DurabilityPublic(BaseModel):
    title: str
    body: str
    image: DurabilityImageRead
    bullets: list[DurabilityBulletPublic]


class DurabilityAdmin(BaseModel):
    title: str
    body: str
    image: DurabilityImageRead
    bullets: list[DurabilityBulletRead]


class DurabilityImageWrite(WriteModel):
    src: str = Field(default="", max_length=255)
    alt: str = Field(default="", max_length=200)

    @field_validator("src", "alt", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class DurabilityBulletWrite(WriteModel):
    text: str = Field(default="", max_length=300)
    is_active: bool = True

    @field_validator("text", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class DurabilityWrite(WriteModel):
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=800)
    image: DurabilityImageWrite
    bullets: list[DurabilityBulletWrite] = Field(default_factory=list, max_length=12)

    @field_validator("title", "body", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
