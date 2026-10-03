from pydantic import BaseModel, Field, field_validator


class ItemPublic(BaseModel):
    id: str
    question: str
    answer: str


class ItemRead(ItemPublic):
    is_active: bool


class FaqPublic(BaseModel):
    title: str
    subtitle: str
    items: list[ItemPublic]


class FaqAdmin(BaseModel):
    is_active: bool
    title: str
    subtitle: str
    items: list[ItemRead]


class ItemWrite(BaseModel):
    question: str = Field(default="", max_length=200)
    answer: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("question", "answer", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class FaqWrite(BaseModel):
    is_active: bool = True
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    items: list[ItemWrite] = Field(default_factory=list, max_length=12)

    @field_validator("title", "subtitle", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
