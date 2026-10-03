import uuid

from pydantic import BaseModel, Field, field_validator


def _href(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if not (
        cleaned.startswith("/") or cleaned.startswith("http://") or cleaned.startswith("https://")
    ):
        raise ValueError("href must start with / or http")
    return cleaned


class StoryParagraphRead(BaseModel):
    id: uuid.UUID
    text: str


class StoryImageRead(BaseModel):
    id: uuid.UUID
    src: str
    alt: str


class StoryRead(BaseModel):
    id: uuid.UUID
    kicker: str
    title: str
    paragraphs: list[StoryParagraphRead]
    cta_label: str
    cta_href: str
    is_active: bool
    images: list[StoryImageRead]


class StoryPublic(BaseModel):
    id: uuid.UUID
    kicker: str
    title: str
    paragraphs: list[StoryParagraphRead]
    cta_label: str
    cta_href: str
    images: list[StoryImageRead]


class StoriesPublic(BaseModel):
    items: list[StoryPublic]


class StoryParagraphWrite(BaseModel):
    text: str = Field(default="", max_length=2000)

    @field_validator("text")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class StoryImageWrite(BaseModel):
    alt: str = Field(default="", max_length=200)
    src: str = Field(default="", max_length=255)

    @field_validator("alt", "src")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class StoryWrite(BaseModel):
    kicker: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    paragraphs: list[StoryParagraphWrite] = Field(default_factory=list)
    cta_label: str = Field(default="", max_length=80)
    cta_href: str = Field(default="", max_length=500)
    is_active: bool = True
    images: list[StoryImageWrite] = Field(default_factory=list)

    @field_validator("kicker", "title", "cta_label")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("cta_href")
    @classmethod
    def _check_href(cls, value: str) -> str:
        return _href(value)

    @field_validator("paragraphs")
    @classmethod
    def _drop_empty(cls, value: list[StoryParagraphWrite]) -> list[StoryParagraphWrite]:
        return [item for item in value if item.text]


class StoryReorder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=12)
