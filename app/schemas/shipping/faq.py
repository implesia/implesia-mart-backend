from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class ItemPublic(BaseModel):
    id: str
    question: str
    answer: str


class ItemRead(ItemPublic):
    is_active: bool


class FaqPublic(BaseModel):
    title: str
    items: list[ItemPublic]
    more_before: str
    more_link_label: str
    more_href: str
    more_after: str


class FaqAdmin(FaqPublic):
    is_active: bool
    items: list[ItemRead]  # type: ignore[assignment]


class ItemWrite(WriteModel):
    id: str | None = None
    question: str = Field(default="", max_length=240)
    answer: str = Field(default="", max_length=2000)
    is_active: bool = True

    @field_validator("question", "answer", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class FaqWrite(WriteModel):
    is_active: bool = True
    title: str = Field(default="", max_length=200)
    items: list[ItemWrite] = Field(default_factory=list, max_length=12)
    more_before: str = Field(default="", max_length=200)
    more_link_label: str = Field(default="", max_length=80)
    more_href: str = Field(default="", max_length=800)
    more_after: str = Field(default="", max_length=200)

    @field_validator(
        "title",
        "more_before",
        "more_link_label",
        "more_href",
        "more_after",
        mode="before",
    )
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
