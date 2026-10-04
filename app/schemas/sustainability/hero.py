import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class SustainabilityHeroImagePublic(BaseModel):
    id: uuid.UUID
    src: str
    alt: str


class SustainabilityHeroImageAdmin(SustainabilityHeroImagePublic):
    sort_order: int


class SustainabilityHeroPublic(BaseModel):
    eyebrow: str
    title: str
    subtitle: str
    primary_label: str
    primary_href: str
    secondary_label: str
    secondary_href: str
    images: list[SustainabilityHeroImagePublic]


class SustainabilityHeroAdmin(BaseModel):
    eyebrow: str
    title: str
    subtitle: str
    primary_label: str
    primary_href: str
    secondary_label: str
    secondary_href: str
    images: list[SustainabilityHeroImageAdmin]


class SustainabilityHeroImageWrite(WriteModel):
    alt: str = Field(default="", max_length=200)
    src: str = Field(default="", max_length=255)

    @field_validator("alt", "src")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class SustainabilityHeroWrite(WriteModel):
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=500)
    primary_label: str = Field(default="", max_length=80)
    primary_href: str = Field(default="", max_length=255)
    secondary_label: str = Field(default="", max_length=80)
    secondary_href: str = Field(default="", max_length=255)
    images: list[SustainabilityHeroImageWrite] = Field(min_length=2, max_length=2)

    @field_validator(
        "eyebrow",
        "title",
        "subtitle",
        "primary_label",
        "primary_href",
        "secondary_label",
        "secondary_href",
    )
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        if not value:
            raise ValueError("Title is required")
        return value
