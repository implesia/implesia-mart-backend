import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class ImpactItemRead(BaseModel):
    id: uuid.UUID
    icon: str
    value: str
    label: str
    is_active: bool


class ImpactItemPublic(BaseModel):
    id: uuid.UUID
    icon: str
    value: str
    label: str


class ImpactAdmin(BaseModel):
    kicker: str
    title: str
    subtitle: str
    items: list[ImpactItemRead]


class ImpactPublic(BaseModel):
    kicker: str
    title: str
    subtitle: str
    items: list[ImpactItemPublic]


class ImpactCopyUpdate(WriteModel):
    kicker: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=160)
    subtitle: str = Field(default="", max_length=400)

    @field_validator("kicker", "title", "subtitle", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ImpactItemWrite(WriteModel):
    icon: str = Field(default="verified", max_length=40)
    value: str = Field(default="", max_length=40)
    label: str = Field(default="", max_length=80)
    is_active: bool = True

    @field_validator("icon", "value", "label", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("icon")
    @classmethod
    def _icon(cls, value: str) -> str:
        return value or "verified"


class ImpactReorder(WriteModel):
    ids: list[uuid.UUID] = Field(max_length=12)
