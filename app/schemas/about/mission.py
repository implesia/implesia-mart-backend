import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel

CardKey = Literal["vision", "mission"]


class MissionCardRead(BaseModel):
    id: uuid.UUID
    key: CardKey
    icon: str
    title: str
    description: str
    is_active: bool


class MissionCardPublic(BaseModel):
    id: uuid.UUID
    key: CardKey
    icon: str
    title: str
    description: str


class MissionPublic(BaseModel):
    items: list[MissionCardPublic]


class MissionCardWrite(WriteModel):
    icon: str = Field(default="verified", max_length=40)
    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("icon", "title", "description", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("icon")
    @classmethod
    def _icon(cls, value: str) -> str:
        return value or "verified"
