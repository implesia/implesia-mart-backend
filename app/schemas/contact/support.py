from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class HourPublic(BaseModel):
    id: str
    label: str
    value: str


class HourRead(HourPublic):
    is_active: bool


class LinkPublic(BaseModel):
    id: str
    icon: str
    label: str
    href: str


class LinkRead(LinkPublic):
    is_active: bool


class SupportPublic(BaseModel):
    title: str
    subtitle: str
    hours: list[HourPublic]
    quick_links: list[LinkPublic]


class SupportAdmin(BaseModel):
    is_active: bool
    title: str
    subtitle: str
    hours: list[HourRead]
    quick_links: list[LinkRead]


class HourWrite(WriteModel):
    label: str = Field(default="", max_length=80)
    value: str = Field(default="", max_length=80)
    is_active: bool = True

    @field_validator("label", "value", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class LinkWrite(WriteModel):
    icon: str = Field(default="help", max_length=40)
    label: str = Field(default="", max_length=80)
    href: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("icon", "label", "href", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class SupportWrite(WriteModel):
    is_active: bool = True
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    hours: list[HourWrite] = Field(default_factory=list, max_length=12)
    quick_links: list[LinkWrite] = Field(default_factory=list, max_length=12)

    @field_validator("title", "subtitle", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
