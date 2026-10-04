from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class CalloutPublic(BaseModel):
    eyebrow: str
    body: str


class CalloutAdmin(CalloutPublic):
    is_active: bool


class CalloutWrite(WriteModel):
    is_active: bool = True
    eyebrow: str = Field(default="", max_length=80)
    body: str = Field(default="", max_length=800)

    @field_validator("eyebrow", "body", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
