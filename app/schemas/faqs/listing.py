from pydantic import BaseModel, Field, field_validator


class ListingPublic(BaseModel):
    count_suffix: str
    empty_title: str
    empty_body: str


class ListingAdmin(ListingPublic):
    is_active: bool


class ListingWrite(BaseModel):
    is_active: bool = True
    count_suffix: str = Field(default="", max_length=80)
    empty_title: str = Field(default="", max_length=200)
    empty_body: str = Field(default="", max_length=800)

    @field_validator("empty_title", "empty_body", mode="before")
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
