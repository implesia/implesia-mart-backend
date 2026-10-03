import uuid

from pydantic import BaseModel, Field, field_validator


class QualityImageRead(BaseModel):
    src: str
    alt: str


class QualityStepPublic(BaseModel):
    id: uuid.UUID
    text: str


class QualityStepRead(QualityStepPublic):
    is_active: bool


class QualityBadgePublic(BaseModel):
    id: uuid.UUID
    icon: str
    label: str


class QualityBadgeRead(QualityBadgePublic):
    is_active: bool


class QualityPublic(BaseModel):
    title: str
    body: str
    image: QualityImageRead
    steps: list[QualityStepPublic]
    badges: list[QualityBadgePublic]


class QualityAdmin(BaseModel):
    title: str
    body: str
    image: QualityImageRead
    steps: list[QualityStepRead]
    badges: list[QualityBadgeRead]


class QualityImageWrite(BaseModel):
    src: str = Field(default="", max_length=255)
    alt: str = Field(default="", max_length=200)

    @field_validator("src", "alt", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class QualityStepWrite(BaseModel):
    text: str = Field(default="", max_length=300)
    is_active: bool = True

    @field_validator("text", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class QualityBadgeWrite(BaseModel):
    icon: str = Field(default="check_circle", max_length=40)
    label: str = Field(default="", max_length=80)
    is_active: bool = True

    @field_validator("icon", "label", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("icon")
    @classmethod
    def _icon(cls, value: str) -> str:
        return value or "check_circle"


class QualityWrite(BaseModel):
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=800)
    image: QualityImageWrite
    steps: list[QualityStepWrite] = Field(default_factory=list, max_length=12)
    badges: list[QualityBadgeWrite] = Field(default_factory=list, max_length=12)

    @field_validator("title", "body", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
