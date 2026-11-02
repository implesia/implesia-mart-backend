import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.badge import BadgeTone
from app.schemas.common import WriteModel

NAME_MAX = 32
MAX_PER_PRODUCT = 8

_BIDI = dict.fromkeys(map(ord, "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"), None)


def clean_name(value: str) -> str:
    """One short line: no control or bidi-override characters, single spaces."""
    text = "".join(ch for ch in value.replace("\x00", "").translate(_BIDI) if ch >= " ")
    text = " ".join(text.split())
    if not text:
        raise ValueError("Badge name is required")
    if len(text) > NAME_MAX:
        raise ValueError(f"Badge name must be at most {NAME_MAX} characters")
    return text


class BadgeWrite(WriteModel):
    name: str = Field(max_length=200)
    tone: BadgeTone = BadgeTone.PRIMARY
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return clean_name(value)


class BadgeUpdate(WriteModel):
    name: str | None = Field(default=None, max_length=200)
    tone: BadgeTone | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else clean_name(value)


class PublicBadge(BaseModel):
    """What a shopper sees. Only active badges are ever returned."""

    name: str
    slug: str
    tone: BadgeTone


class BadgeRef(PublicBadge):
    """A badge as attached to a product in the admin (inactive ones included)."""

    id: uuid.UUID
    is_active: bool


class BadgeAdminRead(BadgeRef):
    is_system: bool
    product_count: int
    created_at: datetime
    updated_at: datetime


class BadgeAdminList(BaseModel):
    items: list[BadgeAdminRead]
