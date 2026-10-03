import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TrustIcon = Literal[
    "payments",
    "local_shipping",
    "assignment_return",
    "verified",
    "local_offer",
    "campaign",
    "shield",
    "support_agent",
    "schedule",
]


def _href(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "/shipping-returns"
    if not (
        cleaned.startswith("/")
        or cleaned.startswith("http://")
        or cleaned.startswith("https://")
    ):
        raise ValueError("href must start with / or http")
    return cleaned


class TrustItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    icon: TrustIcon
    label: str
    href: str
    is_active: bool
    sort_order: int


class TrustItemPublic(BaseModel):
    id: uuid.UUID
    icon: TrustIcon
    label: str
    href: str


class TrustPublic(BaseModel):
    items: list[TrustItemPublic]


class TrustItemWrite(BaseModel):
    icon: TrustIcon = "verified"
    label: str = Field(min_length=1, max_length=120)
    href: str = Field("", max_length=255)
    is_active: bool = True

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Label is required")
        return cleaned

    @field_validator("href")
    @classmethod
    def _check_href(cls, value: str) -> str:
        return _href(value)


class TrustItemUpdate(BaseModel):
    icon: TrustIcon | None = None
    label: str | None = Field(None, min_length=1, max_length=120)
    href: str | None = Field(None, max_length=255)
    is_active: bool | None = None

    @field_validator("label")
    @classmethod
    def _label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Label is required")
        return cleaned

    @field_validator("href")
    @classmethod
    def _check_href(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _href(value)


class TrustReorder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=12)
