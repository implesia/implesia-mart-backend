import re
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.inquiry import InquiryStatus, InquiryType
from app.schemas.common import WriteModel

LIMITS = {"name": 80, "email": 254, "subject": 160, "message": 2000, "note": 2000}

EMPTY_MESSAGE = "Add an email, a phone number or a message so we can get back to you."
EMAIL_MESSAGE = "That email address does not look right."
PHONE_MESSAGE = "Use a Bangladeshi mobile number, for example 01712345678."

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^(?:\+?88)?(01[3-9]\d{8})$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: object, limit: int, *, multiline: bool = False) -> str:
    """Plain text: strip control characters, collapse single-line whitespace, cap length."""
    if value is None:
        return ""
    text = _CONTROL.sub("", str(value))
    text = text.replace("\r\n", "\n").strip() if multiline else " ".join(text.split())
    return text[:limit]


def normalize_phone(value: str) -> str | None:
    """Digits-only 01XXXXXXXXX, or None when it is not a BD mobile number."""
    compact = re.sub(r"[\s\-().]", "", value.translate(_BN_DIGITS))
    match = _PHONE.match(compact)
    return match.group(1) if match else None


class InquiryMeta(BaseModel):
    """Whitelisted context. Unknown keys are dropped, never stored."""

    model_config = ConfigDict(extra="ignore")

    page_path: str = Field("", max_length=200)
    product_id: uuid.UUID | None = None
    product_slug: str = Field("", max_length=120)
    topic: str = Field("", max_length=60)

    @field_validator("page_path", mode="before")
    @classmethod
    def _path(cls, value: object) -> str:
        text = clean_text(value, 200)
        return text if text.startswith("/") and not text.startswith("//") else ""

    @field_validator("product_slug", "topic", mode="before")
    @classmethod
    def _short(cls, value: object) -> str:
        return clean_text(value, 120)


class InquiryCreate(WriteModel):
    """Public submission. Every visitor field is optional; see ``has_content``."""

    type: InquiryType = InquiryType.CONTACT
    name: str = ""
    email: str = ""
    phone: str = ""
    subject: str = ""
    message: str = ""
    meta: InquiryMeta = Field(default_factory=InquiryMeta)
    # Anti-spam: hidden field people never fill, and ms since the form appeared.
    website: str = Field("", max_length=200)
    elapsed_ms: int | None = Field(None, ge=0, le=86_400_000)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: object) -> str:
        return clean_text(value, LIMITS["name"])

    @field_validator("subject", mode="before")
    @classmethod
    def _subject(cls, value: object) -> str:
        return clean_text(value, LIMITS["subject"])

    @field_validator("message", mode="before")
    @classmethod
    def _message(cls, value: object) -> str:
        return clean_text(value, LIMITS["message"], multiline=True)

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: object) -> str:
        text = clean_text(value, LIMITS["email"]).lower()
        if text and not _EMAIL.match(text):
            raise ValueError(EMAIL_MESSAGE)
        return text

    @field_validator("phone", mode="before")
    @classmethod
    def _phone(cls, value: object) -> str:
        text = clean_text(value, 40)
        if not text:
            return ""
        phone = normalize_phone(text)
        if phone is None:
            raise ValueError(PHONE_MESSAGE)
        return phone

    def has_content(self) -> bool:
        return bool(self.email or self.phone or self.message)


class InquiryReceipt(BaseModel):
    id: uuid.UUID
    status: Literal["received"] = "received"


class InquiryAdmin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: uuid.UUID
    type: InquiryType
    status: InquiryStatus
    name: str
    email: str
    phone: str
    subject: str
    message: str
    meta: dict[str, object]
    admin_note: str
    handled_by_id: uuid.UUID | None
    handled_by_name: str = ""
    created_at: datetime
    updated_at: datetime


class InquiryCounts(BaseModel):
    new: int = 0
    in_progress: int = 0
    resolved: int = 0
    total: int = 0


class InquiryList(BaseModel):
    items: list[InquiryAdmin]
    total: int
    page: int
    page_size: int
    pages: int
    counts: InquiryCounts


class InquiryQuery(BaseModel):
    q: str | None = Field(default=None, max_length=80)
    type: InquiryType | None = None
    status: InquiryStatus | None = None
    date_from: date | None = None
    date_to: date | None = None
    sort: Literal["newest", "oldest"] = "newest"
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class InquiryUpdate(WriteModel):
    status: InquiryStatus | None = None
    admin_note: str | None = None

    @field_validator("admin_note", mode="before")
    @classmethod
    def _note(cls, value: object) -> str | None:
        return None if value is None else clean_text(value, LIMITS["note"], multiline=True)
