import uuid

from pydantic import BaseModel, Field, field_validator


class ValueItemRead(BaseModel):
    id: uuid.UUID
    icon: str
    title: str
    description: str
    is_active: bool


class ValueItemPublic(BaseModel):
    id: uuid.UUID
    icon: str
    title: str
    description: str


class ValuesAdmin(BaseModel):
    kicker: str
    title: str
    subtitle: str
    items: list[ValueItemRead]


class ValuesPublic(BaseModel):
    kicker: str
    title: str
    subtitle: str
    items: list[ValueItemPublic]


class ValuesCopyUpdate(BaseModel):
    kicker: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=160)
    subtitle: str = Field(default="", max_length=400)

    @field_validator("kicker", "title", "subtitle", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ValueItemWrite(BaseModel):
    icon: str = Field(default="verified", max_length=40)
    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=400)
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


class ValueReorder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=12)
