from pydantic import BaseModel, Field, field_validator


class HeroPublic(BaseModel):
    eyebrow: str
    title: str
    subtitle: str
    count_label: str


class HeroAdmin(HeroPublic):
    is_active: bool


class HeroWrite(BaseModel):
    is_active: bool = True
    eyebrow: str = Field(default="", max_length=80)
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    count_label: str = Field(default="", max_length=80)

    @field_validator("eyebrow", "title", "subtitle", "count_label", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
