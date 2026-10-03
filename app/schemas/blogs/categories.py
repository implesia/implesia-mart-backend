from pydantic import BaseModel, Field, field_validator


class ItemPublic(BaseModel):
    id: str
    label: str


class ItemRead(ItemPublic):
    is_active: bool


class CategoriesPublic(BaseModel):
    items: list[ItemPublic]


class CategoriesAdmin(BaseModel):
    is_active: bool
    items: list[ItemRead]


class ItemWrite(BaseModel):
    id: str | None = None
    label: str = Field(default="", max_length=80)
    is_active: bool = True

    @field_validator("label", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CategoriesWrite(BaseModel):
    is_active: bool = True
    items: list[ItemWrite] = Field(default_factory=list, max_length=12)
