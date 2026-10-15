import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel
from app.schemas.sustainability.optional_image import OptionalImageWrite


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
    # src is "" when the section has no photo (shape kept for older clients).
    image: DurabilityImageRead
    # 0 or 1 item, same as other sustainability sections.
    images: list[DurabilityImageRead] = Field(default_factory=list)
    bullets: list[DurabilityBulletPublic]


class DurabilityAdmin(BaseModel):
    title: str
    body: str
    # src is "" when the section has no photo (shape kept for older clients).
    image: DurabilityImageRead
    # 0 or 1 item, same as other sustainability sections.
    images: list[DurabilityImageRead] = Field(default_factory=list)
    bullets: list[DurabilityBulletRead]


DurabilityImageWrite = OptionalImageWrite


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
    image: DurabilityImageWrite | None = None
    bullets: list[DurabilityBulletWrite] = Field(default_factory=list, max_length=12)

    @field_validator("title", "body", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
