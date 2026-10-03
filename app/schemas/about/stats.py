import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StatIcon = Literal[
    "payments",
    "local_shipping",
    "assignment_return",
    "verified",
    "category",
    "location_on",
    "design_services",
    "back_hand",
    "checkroom",
    "visibility",
    "rocket_launch",
    "search",
    "task_alt",
    "storefront",
    "support_agent",
    "favorite",
    "shield",
]


class StatItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    icon: StatIcon
    value: str
    label: str
    is_active: bool
    sort_order: int


class StatItemPublic(BaseModel):
    id: uuid.UUID
    icon: StatIcon
    value: str
    label: str


class StatsPublic(BaseModel):
    items: list[StatItemPublic]


class StatItemWrite(BaseModel):
    icon: StatIcon = "verified"
    value: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    is_active: bool = True

    @field_validator("value", "label")
    @classmethod
    def _required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This field is required")
        return cleaned


class StatItemUpdate(BaseModel):
    icon: StatIcon | None = None
    value: str | None = Field(None, min_length=1, max_length=40)
    label: str | None = Field(None, min_length=1, max_length=80)
    is_active: bool | None = None

    @field_validator("value", "label")
    @classmethod
    def _required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This field is required")
        return cleaned


class StatReorder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=12)
