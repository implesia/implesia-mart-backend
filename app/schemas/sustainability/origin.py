import uuid

from pydantic import BaseModel, Field, field_validator

from app.schemas.sustainability.optional_image import OptionalImageMixin, OptionalImageWrite


class OriginImagePublic(BaseModel):
    id: uuid.UUID
    src: str
    alt: str


class OriginImageAdmin(OriginImagePublic):
    is_active: bool


class OriginPublic(BaseModel):
    eyebrow: str
    title: str
    body: str
    quote: str
    image: OriginImagePublic | None = None
    # Legacy mirror of `image` (0 or 1 item) for clients from before 0072.
    images: list[OriginImagePublic]


class OriginAdmin(BaseModel):
    eyebrow: str
    title: str
    body: str
    quote: str
    image: OriginImageAdmin | None = None
    images: list[OriginImageAdmin]


OriginImageWrite = OptionalImageWrite


class OriginWrite(OptionalImageMixin):
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=800)
    quote: str = Field(default="", max_length=400)

    @field_validator("eyebrow", "title", "body", "quote", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
