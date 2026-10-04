from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class ContentsPublic(BaseModel):
    title: str
    subtitle: str
    nav_label: str


class ContentsAdmin(ContentsPublic):
    is_active: bool


class ContentsWrite(WriteModel):
    is_active: bool = True
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    nav_label: str = Field(default="", max_length=80)

    @field_validator("title", "subtitle", "nav_label", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
