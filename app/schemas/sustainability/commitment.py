import uuid

from pydantic import BaseModel, Field, field_validator


class CommitmentItemRead(BaseModel):
    id: uuid.UUID
    icon: str
    title: str
    description: str
    is_active: bool


class CommitmentItemPublic(BaseModel):
    id: uuid.UUID
    icon: str
    title: str
    description: str


class CommitmentAdmin(BaseModel):
    kicker: str
    title: str
    subtitle: str
    items: list[CommitmentItemRead]


class CommitmentPublic(BaseModel):
    kicker: str
    title: str
    subtitle: str
    items: list[CommitmentItemPublic]


class CommitmentCopyUpdate(BaseModel):
    kicker: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=160)
    subtitle: str = Field(default="", max_length=400)

    @field_validator("kicker", "title", "subtitle", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CommitmentItemWrite(BaseModel):
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


class CommitmentReorder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=12)
