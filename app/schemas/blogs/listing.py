from pydantic import BaseModel, Field, field_validator


class ListingPublic(BaseModel):
    heading: str
    all_label: str
    count_suffix: str
    empty_message: str
    featured_label: str
    read_label: str
    read_suffix: str
    tabs_label: str


class ListingAdmin(ListingPublic):
    is_active: bool


class ListingWrite(BaseModel):
    is_active: bool = True
    heading: str = Field(default="", max_length=200)
    all_label: str = Field(default="", max_length=80)
    count_suffix: str = Field(default="", max_length=80)
    empty_message: str = Field(default="", max_length=400)
    featured_label: str = Field(default="", max_length=80)
    read_label: str = Field(default="", max_length=80)
    read_suffix: str = Field(default="", max_length=80)
    tabs_label: str = Field(default="", max_length=80)

    @field_validator(
        "heading",
        "all_label",
        "empty_message",
        "featured_label",
        "read_label",
        "read_suffix",
        "tabs_label",
        mode="before",
    )
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("count_suffix", mode="before")
    @classmethod
    def _suffix(cls, value: object) -> object:
        if isinstance(value, str):
            return value.rstrip()
        return value
