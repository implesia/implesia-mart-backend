import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.about.single_image import SingleImageMixin, SingleImageWrite


class AboutHeroImagePublic(BaseModel):
    id: uuid.UUID
    src: str
    alt: str


class AboutHeroImageAdmin(AboutHeroImagePublic):
    sort_order: int


class AboutHeroPublic(BaseModel):
    eyebrow: str
    title: str
    subtitle: str
    primary_label: str
    primary_href: str
    secondary_label: str
    secondary_href: str
    image: AboutHeroImagePublic | None = None
    # Deprecated mirror of `image` (0 or 1 item) for storefront builds that read `images`.
    images: list[AboutHeroImagePublic]


class AboutHeroAdmin(BaseModel):
    eyebrow: str
    title: str
    subtitle: str
    primary_label: str
    primary_href: str
    secondary_label: str
    secondary_href: str
    image: AboutHeroImageAdmin | None = None
    images: list[AboutHeroImageAdmin]


AboutHeroImageWrite = SingleImageWrite


class AboutHeroWrite(SingleImageMixin):
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=500)
    primary_label: str = Field(default="", max_length=80)
    primary_href: str = Field(default="", max_length=255)
    secondary_label: str = Field(default="", max_length=80)
    secondary_href: str = Field(default="", max_length=255)

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
