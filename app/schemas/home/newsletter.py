import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import WriteModel

NewsletterIcon = Literal[
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


class NewsletterPerkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    icon: NewsletterIcon
    label: str
    is_active: bool
    sort_order: int


class NewsletterPerkPublic(BaseModel):
    id: uuid.UUID
    icon: NewsletterIcon
    label: str


class NewsletterAdmin(BaseModel):
    eyebrow: str
    title: str
    subtitle: str
    placeholder: str
    cta: str
    success: str
    perks: list[NewsletterPerkRead]


class NewsletterPublic(BaseModel):
    eyebrow: str
    title: str
    subtitle: str
    placeholder: str
    cta: str
    success: str
    perks: list[NewsletterPerkPublic]


class NewsletterCopyUpdate(WriteModel):
    eyebrow: str = Field(max_length=80)
    title: str = Field(max_length=160)
    subtitle: str = Field(max_length=400)
    placeholder: str = Field(max_length=80)
    cta: str = Field(max_length=40)
    success: str = Field(max_length=200)

    @field_validator("eyebrow", "title", "subtitle", "placeholder", "cta", "success")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class NewsletterPerkWrite(WriteModel):
    icon: NewsletterIcon = "local_offer"
    label: str = Field(min_length=1, max_length=120)
    is_active: bool = True

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Label is required")
        return cleaned


class NewsletterPerkUpdate(WriteModel):
    icon: NewsletterIcon | None = None
    label: str | None = Field(None, min_length=1, max_length=120)
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


class NewsletterReorder(WriteModel):
    ids: list[uuid.UUID] = Field(max_length=12)
