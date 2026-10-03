from pydantic import BaseModel, Field, field_validator


class HeroPublic(BaseModel):
    eyebrow: str
    title: str
    subtitle: str
    updated_label: str
    last_updated: str


class HeroAdmin(HeroPublic):
    is_active: bool


class HeroWrite(BaseModel):
    is_active: bool = True
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    updated_label: str = Field(default="", max_length=80)
    last_updated: str = Field(default="", max_length=80)

    @field_validator(
        "eyebrow", "title", "subtitle", "updated_label", "last_updated", mode="before"
    )
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
