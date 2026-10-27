import re

from pydantic import BaseModel, ValidationInfo, field_validator

from app.schemas.common import WriteModel

_LOCAL = re.compile(r"01[3-9]\d{8}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_SEPARATORS = re.compile(r"[\s\-().]")


def normalize_phone(value: str) -> str | None:
    """A Bangladesh mobile number in any common spelling -> 01XXXXXXXXX, or None."""
    digits = _SEPARATORS.sub("", value or "")
    if digits.startswith("+"):
        digits = digits[1:]
    if re.fullmatch(r"8801[3-9]\d{8}", digits):
        digits = "0" + digits[3:]
    return digits if _LOCAL.fullmatch(digits) else None


def normalize_email(value: str) -> str | None:
    email = (value or "").strip().lower()
    if len(email) > 254 or not _EMAIL.fullmatch(email):
        return None
    return email


class SiteContactWrite(WriteModel):
    phone: str
    whatsapp: str
    email: str

    @field_validator("phone", "whatsapp", mode="before")
    @classmethod
    def _number(cls, value: object, info: ValidationInfo) -> str:
        label = "Phone" if info.field_name == "phone" else "WhatsApp"
        number = normalize_phone(value) if isinstance(value, str) else None
        if number is None:
            raise ValueError(f"{label} must be a Bangladesh mobile number such as 01580569129")
        return number

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: object) -> str:
        email = normalize_email(value) if isinstance(value, str) else None
        if email is None:
            raise ValueError("Enter a valid email address such as name@example.com")
        return email


class SiteContactPublic(BaseModel):
    """What the storefront renders. The links are derived from the stored values."""

    phone: str
    whatsapp: str
    email: str
    tel_href: str
    whatsapp_href: str
    mailto_href: str


class SiteContactAdmin(SiteContactPublic):
    is_default: bool = False
