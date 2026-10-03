import uuid

from pydantic import BaseModel, Field, field_validator


class StepItemRead(BaseModel):
    id: uuid.UUID
    step: str
    icon: str
    title: str
    description: str
    is_active: bool


class StepItemPublic(BaseModel):
    id: uuid.UUID
    step: str
    icon: str
    title: str
    description: str


class StepsAdmin(BaseModel):
    kicker: str
    title: str
    subtitle: str
    items: list[StepItemRead]


class StepsPublic(BaseModel):
    kicker: str
    title: str
    subtitle: str
    items: list[StepItemPublic]


class StepsCopyUpdate(BaseModel):
    kicker: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=160)
    subtitle: str = Field(default="", max_length=400)

    @field_validator("kicker", "title", "subtitle", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class StepItemWrite(BaseModel):
    step: str = Field(default="", max_length=20)
    icon: str = Field(default="task_alt", max_length=40)
    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=400)
    is_active: bool = True

    @field_validator("step", "icon", "title", "description", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("icon")
    @classmethod
    def _icon(cls, value: str) -> str:
        return value or "task_alt"


class StepReorder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=12)
