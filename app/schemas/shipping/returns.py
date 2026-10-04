from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class RulePublic(BaseModel):
    id: str
    text: str


class RuleRead(RulePublic):
    is_active: bool


class NotePublic(BaseModel):
    id: str
    icon: str
    title: str
    body: str


class NoteRead(NotePublic):
    is_active: bool


class ReturnsPublic(BaseModel):
    icon: str
    nav_label: str
    heading: str
    eligibility_title: str
    eligibility_body: str
    rules: list[RulePublic]
    notes: list[NotePublic]


class ReturnsAdmin(ReturnsPublic):
    is_active: bool
    rules: list[RuleRead]  # type: ignore[assignment]
    notes: list[NoteRead]  # type: ignore[assignment]


class RuleWrite(WriteModel):
    id: str | None = None
    text: str = Field(default="", max_length=400)
    is_active: bool = True

    @field_validator("text", mode="before")
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


class ReturnsWrite(WriteModel):
    is_active: bool = True
    icon: str = Field(default="", max_length=40)
    nav_label: str = Field(default="", max_length=80)
    heading: str = Field(default="", max_length=200)
    eligibility_title: str = Field(default="", max_length=200)
    eligibility_body: str = Field(default="", max_length=800)
    rules: list[RuleWrite] = Field(default_factory=list, max_length=12)
    notes: list[NoteWrite] = Field(default_factory=list, max_length=12)

    @field_validator(
        "icon",
        "nav_label",
        "heading",
        "eligibility_title",
        "eligibility_body",
        mode="before",
    )
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
