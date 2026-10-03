from pydantic import BaseModel, Field, field_validator


class CardPublic(BaseModel):
    id: str
    icon: str
    title: str
    description: str


class CardRead(CardPublic):
    is_active: bool


class CollectionPublic(BaseModel):
    icon: str
    nav_label: str
    heading: str
    intro: str
    cards: list[CardPublic]


class CollectionAdmin(CollectionPublic):
    is_active: bool
    cards: list[CardRead]


class CardWrite(BaseModel):
    id: str | None = None
    icon: str = Field(default="", max_length=40)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("icon", "title", "description", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class CollectionWrite(BaseModel):
    is_active: bool = True
    icon: str = Field(default="", max_length=40)
    nav_label: str = Field(default="", max_length=80)
    heading: str = Field(default="", max_length=200)
    intro: str = Field(default="", max_length=800)
    cards: list[CardWrite] = Field(default_factory=list, max_length=12)

    @field_validator("icon", "nav_label", "heading", "intro", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
