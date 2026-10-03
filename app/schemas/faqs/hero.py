from pydantic import BaseModel, Field, field_validator


class SearchPublic(BaseModel):
    id: str
    label: str


class SearchRead(SearchPublic):
    is_active: bool


class HeroPublic(BaseModel):
    eyebrow: str
    title: str
    subtitle: str
    placeholder: str
    search_label: str
    clear_label: str
    trending_label: str
    trending: list[SearchPublic]


class HeroAdmin(HeroPublic):
    is_active: bool
    trending: list[SearchRead]


class SearchWrite(BaseModel):
    id: str | None = None
    label: str = Field(default="", max_length=80)
    is_active: bool = True

    @field_validator("label", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class HeroWrite(BaseModel):
    is_active: bool = True
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    placeholder: str = Field(default="", max_length=200)
    search_label: str = Field(default="", max_length=80)
    clear_label: str = Field(default="", max_length=80)
    trending_label: str = Field(default="", max_length=80)
    trending: list[SearchWrite] = Field(default_factory=list, max_length=12)

    @field_validator(
        "eyebrow",
        "title",
        "subtitle",
        "placeholder",
        "search_label",
        "clear_label",
        "trending_label",
        mode="before",
    )
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
