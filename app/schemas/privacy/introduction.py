from pydantic import BaseModel, Field, field_validator


class ParagraphPublic(BaseModel):
    id: str
    text: str


class ParagraphRead(ParagraphPublic):
    is_active: bool


class IntroductionPublic(BaseModel):
    icon: str
    nav_label: str
    heading: str
    paragraphs: list[ParagraphPublic]


class IntroductionAdmin(IntroductionPublic):
    is_active: bool
    paragraphs: list[ParagraphRead]


class ParagraphWrite(BaseModel):
    id: str | None = None
    text: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("text", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class IntroductionWrite(BaseModel):
    is_active: bool = True
    icon: str = Field(default="", max_length=40)
    nav_label: str = Field(default="", max_length=80)
    heading: str = Field(default="", max_length=200)
    paragraphs: list[ParagraphWrite] = Field(default_factory=list, max_length=12)

    @field_validator("icon", "nav_label", "heading", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
