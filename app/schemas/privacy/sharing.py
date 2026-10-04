from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class ChipPublic(BaseModel):
    id: str
    label: str


class ChipRead(ChipPublic):
    is_active: bool


class SharingPublic(BaseModel):
    icon: str
    nav_label: str
    heading: str
    body: str
    chips: list[ChipPublic]


class SharingAdmin(SharingPublic):
    is_active: bool
    chips: list[ChipRead]  # type: ignore[assignment]


class ChipWrite(WriteModel):
    id: str | None = None
    label: str = Field(default="", max_length=80)
    is_active: bool = True

    @field_validator("label", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class SharingWrite(WriteModel):
    is_active: bool = True
    icon: str = Field(default="", max_length=40)
    nav_label: str = Field(default="", max_length=80)
    heading: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=800)
    chips: list[ChipWrite] = Field(default_factory=list, max_length=12)

    @field_validator("icon", "nav_label", "heading", "body", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
