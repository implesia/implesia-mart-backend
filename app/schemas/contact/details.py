from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class ChannelPublic(BaseModel):
    id: str
    icon: str
    title: str
    value: str
    href: str


class ChannelRead(ChannelPublic):
    is_active: bool


class SocialPublic(BaseModel):
    platform: Literal["facebook", "linkedin"]
    label: str
    href: str


class SocialRead(SocialPublic):
    is_active: bool


class DetailsPublic(BaseModel):
    title: str
    subtitle: str
    badge: str
    channels: list[ChannelPublic]
    social: list[SocialPublic]


class DetailsAdmin(BaseModel):
    is_active: bool
    title: str
    subtitle: str
    badge: str
    channels: list[ChannelRead]
    social: list[SocialRead]


class ChannelWrite(WriteModel):
    icon: str = Field(default="call", max_length=40)
    title: str = Field(default="", max_length=80)
    value: str = Field(default="", max_length=160)
    href: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("icon", "title", "value", "href", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class SocialWrite(WriteModel):
    platform: Literal["facebook", "linkedin"]
    label: str = Field(default="", max_length=80)
    href: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("label", "href", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class DetailsWrite(WriteModel):
    is_active: bool = True
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    badge: str = Field(default="", max_length=80)
    channels: list[ChannelWrite] = Field(default_factory=list, max_length=12)
    social: list[SocialWrite] = Field(default_factory=list, max_length=2)

    @field_validator("title", "subtitle", "badge", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
