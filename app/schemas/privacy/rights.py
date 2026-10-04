from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class ItemPublic(BaseModel):
    id: str
    icon: str
    title: str
    description: str


class ItemRead(ItemPublic):
    is_active: bool


class NotePublic(BaseModel):
    title: str
    body: str


class NoteRead(NotePublic):
    is_active: bool


class RightsPublic(BaseModel):
    icon: str
    nav_label: str
    heading: str
    intro: str
    items: list[ItemPublic]
    retention: NotePublic
    updates: NotePublic


class RightsAdmin(RightsPublic):
    is_active: bool
    items: list[ItemRead]  # type: ignore[assignment]
    retention: NoteRead
    updates: NoteRead


class ItemWrite(WriteModel):
    id: str | None = None
    icon: str = Field(default="", max_length=40)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("icon", "title", "description", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class NoteWrite(WriteModel):
    is_active: bool = True
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=800)

    @field_validator("title", "body", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class RightsWrite(WriteModel):
    is_active: bool = True
    icon: str = Field(default="", max_length=40)
    nav_label: str = Field(default="", max_length=80)
    heading: str = Field(default="", max_length=200)
    intro: str = Field(default="", max_length=800)
    items: list[ItemWrite] = Field(default_factory=list, max_length=12)
    retention: NoteWrite = Field(default_factory=NoteWrite)
    updates: NoteWrite = Field(default_factory=NoteWrite)

    @field_validator("icon", "nav_label", "heading", "intro", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
