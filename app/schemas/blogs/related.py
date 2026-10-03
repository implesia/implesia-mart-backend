from pydantic import BaseModel, Field, field_validator


class RelatedPublic(BaseModel):
    toc_title: str
    products_title: str
    products_subtitle: str
    posts_title: str
    posts_subtitle: str
    posts_link_label: str
    coming_soon_label: str
    view_label: str
    details_label: str


class RelatedAdmin(RelatedPublic):
    is_active: bool


class RelatedWrite(BaseModel):
    is_active: bool = True
    toc_title: str = Field(default="", max_length=120)
    products_title: str = Field(default="", max_length=200)
    products_subtitle: str = Field(default="", max_length=400)
    posts_title: str = Field(default="", max_length=200)
    posts_subtitle: str = Field(default="", max_length=200)
    posts_link_label: str = Field(default="", max_length=80)
    coming_soon_label: str = Field(default="", max_length=80)
    view_label: str = Field(default="", max_length=80)
    details_label: str = Field(default="", max_length=80)

    @field_validator(
        "toc_title",
        "products_title",
        "products_subtitle",
        "posts_title",
        "posts_subtitle",
        "posts_link_label",
        "coming_soon_label",
        "view_label",
        "details_label",
        mode="before",
    )
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
