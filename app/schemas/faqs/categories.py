from pydantic import BaseModel, Field, field_validator

from app.schemas.common import WriteModel


class ItemPublic(BaseModel):
    id: str
    label: str
    icon: str


class ItemRead(ItemPublic):
    is_active: bool


class CategoriesPublic(BaseModel):
    title: str
    subtitle: str
    all_label: str
    all_icon: str
    nav_label: str
    items: list[ItemPublic]


class CategoriesAdmin(CategoriesPublic):
    is_active: bool
    items: list[ItemRead]  # type: ignore[assignment]


class ItemWrite(WriteModel):
    id: str | None = None
    label: str = Field(default="", max_length=80)
    icon: str = Field(default="", max_length=40)
    is_active: bool = True

    @field_validator("label", "icon", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CategoriesWrite(WriteModel):
    is_active: bool = True
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    all_label: str = Field(default="", max_length=80)
    all_icon: str = Field(default="", max_length=40)
    nav_label: str = Field(default="", max_length=80)
    items: list[ItemWrite] = Field(default_factory=list, max_length=12)

    @field_validator("title", "subtitle", "all_label", "all_icon", "nav_label", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
