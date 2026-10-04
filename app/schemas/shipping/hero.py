from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class HeroPublic(BaseModel):
    eyebrow: str
    title: str
    subtitle: str


class HeroAdmin(HeroPublic):
    is_active: bool


class HeroWrite(WriteModel):
    is_active: bool = True
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)

    @field_validator("eyebrow", "title", "subtitle", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
