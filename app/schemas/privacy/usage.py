from pydantic import BaseModel, Field, field_validator


class ItemPublic(BaseModel):
    id: str
    title: str
    description: str


class ItemRead(ItemPublic):
    is_active: bool


class BadgePublic(BaseModel):
    id: str
    icon: str
    label: str


class BadgeRead(BadgePublic):
    is_active: bool


class ProtectionPublic(BaseModel):
    icon: str
    title: str
    body: str
    badges: list[BadgePublic]


class ProtectionRead(ProtectionPublic):
    is_active: bool
    badges: list[BadgeRead]


class UsagePublic(BaseModel):
    icon: str
    nav_label: str
    heading: str
    intro: str
    items: list[ItemPublic]
    protection: ProtectionPublic


class UsageAdmin(UsagePublic):
    is_active: bool
    items: list[ItemRead]
    protection: ProtectionRead


class ItemWrite(BaseModel):
    id: str | None = None
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=800)
    is_active: bool = True

    @field_validator("title", "description", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class BadgeWrite(BaseModel):
    id: str | None = None
    icon: str = Field(default="", max_length=40)
    label: str = Field(default="", max_length=80)
    is_active: bool = True

    @field_validator("icon", "label", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ProtectionWrite(BaseModel):
    is_active: bool = True
    icon: str = Field(default="", max_length=40)
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=800)
    badges: list[BadgeWrite] = Field(default_factory=list, max_length=12)

    @field_validator("icon", "title", "body", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class UsageWrite(BaseModel):
    is_active: bool = True
    icon: str = Field(default="", max_length=40)
    nav_label: str = Field(default="", max_length=80)
    heading: str = Field(default="", max_length=200)
    intro: str = Field(default="", max_length=800)
    items: list[ItemWrite] = Field(default_factory=list, max_length=12)
    protection: ProtectionWrite = Field(default_factory=ProtectionWrite)

    @field_validator("icon", "nav_label", "heading", "intro", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
