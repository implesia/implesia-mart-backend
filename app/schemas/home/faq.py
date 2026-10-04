import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import WriteModel


def _href(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "/faqs"
    if not (
        cleaned.startswith("/") or cleaned.startswith("http://") or cleaned.startswith("https://")
    ):
        raise ValueError("href must start with / or http")
    return cleaned


class FaqItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    question: str
    answer: str
    is_active: bool
    sort_order: int


class FaqItemPublic(BaseModel):
    id: uuid.UUID
    category: str
    question: str
    answer: str


class FaqAdmin(BaseModel):
    kicker: str
    title: str
    subtitle: str
    more_label: str
    more_href: str
    items: list[FaqItemRead]


class FaqPublic(BaseModel):
    kicker: str
    title: str
    subtitle: str
    more_label: str
    more_href: str
    items: list[FaqItemPublic]


class FaqCopyUpdate(WriteModel):
    kicker: str = Field(max_length=80)
    title: str = Field(max_length=160)
    subtitle: str = Field(max_length=400)
    more_label: str = Field(max_length=80)
    more_href: str = Field(max_length=255)

    @field_validator("kicker", "title", "subtitle", "more_label")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("more_href")
    @classmethod
    def _more_href(cls, value: str) -> str:
        return _href(value)


class FaqItemWrite(WriteModel):
    category: str = Field("", max_length=80)
    question: str = Field(min_length=1, max_length=240)
    answer: str = Field(min_length=1, max_length=2000)
    is_active: bool = True

    @field_validator("category")
    @classmethod
    def _category(cls, value: str) -> str:
        return value.strip()

    @field_validator("question")
    @classmethod
    def _question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question is required")
        return cleaned

    @field_validator("answer")
    @classmethod
    def _answer(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Answer is required")
        return cleaned


class FaqItemUpdate(WriteModel):
    category: str | None = Field(None, max_length=80)
    question: str | None = Field(None, min_length=1, max_length=240)
    answer: str | None = Field(None, min_length=1, max_length=2000)
    is_active: bool | None = None

    @field_validator("category")
    @classmethod
    def _category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("question")
    @classmethod
    def _question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question is required")
        return cleaned

    @field_validator("answer")
    @classmethod
    def _answer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Answer is required")
        return cleaned


class FaqReorder(WriteModel):
    ids: list[uuid.UUID] = Field(max_length=24)
