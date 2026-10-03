from pydantic import BaseModel, Field, field_validator


class StepPublic(BaseModel):
    id: str
    title: str
    body: str


class StepRead(StepPublic):
    is_active: bool


class RefundPublic(BaseModel):
    icon: str
    nav_label: str
    heading: str
    steps: list[StepPublic]
    note: str


class RefundAdmin(RefundPublic):
    is_active: bool
    steps: list[StepRead]


class StepWrite(BaseModel):
    id: str | None = None
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("title", "body", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class RefundWrite(BaseModel):
    is_active: bool = True
    icon: str = Field(default="", max_length=40)
    nav_label: str = Field(default="", max_length=80)
    heading: str = Field(default="", max_length=200)
    steps: list[StepWrite] = Field(default_factory=list, max_length=12)
    note: str = Field(default="", max_length=800)

    @field_validator("icon", "nav_label", "heading", "note", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
