from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class CardPublic(BaseModel):
    id: str
    icon: str
    eyebrow: str
    title: str
    body: str
    variant: str


class CardRead(CardPublic):
    is_active: bool


class TimePublic(BaseModel):
    id: str
    label: str
    value: str


class TimeRead(TimePublic):
    is_active: bool


class NotePublic(BaseModel):
    id: str
    icon: str
    title: str
    body: str


class NoteRead(NotePublic):
    is_active: bool


class BlockPublic(BaseModel):
    icon: str
    nav_label: str
    heading: str
    intro: str
    cards: list[CardPublic]
    timelines_title: str
    timelines: list[TimePublic]
    notes: list[NotePublic]


class BlockAdmin(BlockPublic):
    is_active: bool
    cards: list[CardRead]  # type: ignore[assignment]
    timelines: list[TimeRead]  # type: ignore[assignment]
    notes: list[NoteRead]  # type: ignore[assignment]


class CardWrite(WriteModel):
    id: str | None = None
    icon: str = Field(default="", max_length=40)
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=800)
    variant: str = "default"
    is_active: bool = True

    @field_validator("icon", "eyebrow", "title", "body", "variant", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class TimeWrite(WriteModel):
    id: str | None = None
    label: str = Field(default="", max_length=120)
    value: str = Field(default="", max_length=80)
    is_active: bool = True

    @field_validator("label", "value", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class NoteWrite(WriteModel):
    id: str | None = None
    icon: str = Field(default="", max_length=40)
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("icon", "title", "body", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class BlockWrite(WriteModel):
    is_active: bool = True
    icon: str = Field(default="", max_length=40)
    nav_label: str = Field(default="", max_length=80)
    heading: str = Field(default="", max_length=200)
    intro: str = Field(default="", max_length=800)
    cards: list[CardWrite] = Field(default_factory=list, max_length=12)
    timelines_title: str = Field(default="", max_length=200)
    timelines: list[TimeWrite] = Field(default_factory=list, max_length=12)
    notes: list[NoteWrite] = Field(default_factory=list, max_length=12)

    @field_validator("icon", "nav_label", "heading", "intro", "timelines_title", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
