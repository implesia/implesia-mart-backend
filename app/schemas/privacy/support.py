from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class SupportPublic(BaseModel):
    icon: str
    nav_label: str
    title: str
    subtitle: str
    email: str
    phone: str
    primary_label: str
    primary_href: str
    secondary_label: str
    secondary_href: str


class SupportAdmin(SupportPublic):
    is_active: bool


class SupportWrite(WriteModel):
    is_active: bool = True
    icon: str = Field(default="", max_length=40)
    nav_label: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=40)
    primary_label: str = Field(default="", max_length=80)
    primary_href: str = Field(default="", max_length=800)
    secondary_label: str = Field(default="", max_length=80)
    secondary_href: str = Field(default="", max_length=800)

    @field_validator(
        "icon",
        "nav_label",
        "title",
        "subtitle",
        "email",
        "phone",
        "primary_label",
        "primary_href",
        "secondary_label",
        "secondary_href",
        mode="before",
    )
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
