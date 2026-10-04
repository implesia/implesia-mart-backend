from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class HeroLink(BaseModel):
    label: str
    href: str


class HeroPublic(BaseModel):
    eyebrow: str
    title: str
    subtitle: str
    primary_cta: HeroLink
    secondary_cta: HeroLink


class HeroAdmin(HeroPublic):
    is_active: bool


class HeroLinkWrite(WriteModel):
    label: str = Field(default="", max_length=80)
    href: str = Field(default="", max_length=800)

    @field_validator("label", "href", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class HeroWrite(WriteModel):
    is_active: bool = True
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    primary_cta: HeroLinkWrite = Field(default_factory=HeroLinkWrite)
    secondary_cta: HeroLinkWrite = Field(default_factory=HeroLinkWrite)

    @field_validator("eyebrow", "title", "subtitle", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
