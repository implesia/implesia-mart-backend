from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class CtaLink(BaseModel):
    label: str
    href: str


class CtaRead(BaseModel):
    title: str
    subtitle: str
    primary_cta: CtaLink
    secondary_cta: CtaLink


class CtaLinkWrite(WriteModel):
    label: str = Field(default="", max_length=80)
    href: str = Field(default="", max_length=800)

    @field_validator("label", "href", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CtaWrite(WriteModel):
    title: str = Field(default="", max_length=160)
    subtitle: str = Field(default="", max_length=400)
    primary_cta: CtaLinkWrite = Field(default_factory=CtaLinkWrite)
    secondary_cta: CtaLinkWrite = Field(default_factory=CtaLinkWrite)

    @field_validator("title", "subtitle", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
