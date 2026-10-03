import uuid

from pydantic import BaseModel, Field, field_validator


class ItemPublic(BaseModel):
    id: str
    category_id: str | None
    question: str
    answer: str


class ItemRead(ItemPublic):
    is_active: bool


class ItemsPublic(BaseModel):
    items: list[ItemPublic]


class ItemsAdmin(BaseModel):
    items: list[ItemRead]


class ItemWrite(BaseModel):
    category_id: str = ""
    question: str = Field(default="", max_length=240)
    answer: str = Field(default="", max_length=2000)
    is_active: bool = True

    @field_validator("category_id", "question", "answer", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ItemReorder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=40)
