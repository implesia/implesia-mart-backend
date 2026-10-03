import re
import uuid

from pydantic import BaseModel, Field, field_validator

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _strip(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


class BlockPublic(BaseModel):
    id: str
    type: str
    text: str
    title: str
    variant: str
    items: list[str]


class BlockAdmin(BlockPublic):
    is_active: bool


class BlockWrite(BaseModel):
    type: str
    text: str = Field(default="", max_length=4000)
    title: str = Field(default="", max_length=200)
    variant: str = "tip"
    items: list[str] = Field(default_factory=list, max_length=20)
    is_active: bool = True

    @field_validator("text", "title", "variant", mode="before")
    @classmethod
    def _clean(cls, value: object) -> object:
        return _strip(value)

    @field_validator("items", mode="before")
    @classmethod
    def _items(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [item.strip() for item in value if isinstance(item, str)]


class PostPublic(BaseModel):
    id: str
    slug: str
    title: str
    excerpt: str
    category_id: str | None
    cover_image: str
    cover_alt: str
    author: str
    author_role: str
    published_at: str
    read_time: str
    tags: list[str]
    related_product_slugs: list[str]
    blocks: list[BlockPublic]


class PostAdmin(PostPublic):
    is_active: bool
    blocks: list[BlockAdmin]


class PostsPublic(BaseModel):
    posts: list[PostPublic]


class PostsAdmin(BaseModel):
    posts: list[PostAdmin]


class PostWrite(BaseModel):
    is_active: bool = True
    slug: str = Field(max_length=160)
    title: str = Field(default="", max_length=200)
    excerpt: str = Field(default="", max_length=500)
    category_id: str = ""
    cover_image: str = Field(default="", max_length=800)
    cover_alt: str = Field(default="", max_length=200)
    author: str = Field(default="", max_length=80)
    author_role: str = Field(default="", max_length=80)
    published_at: str = Field(default="", max_length=40)
    read_time: str = Field(default="", max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=12)
    related_product_slugs: list[str] = Field(default_factory=list, max_length=8)
    blocks: list[BlockWrite] = Field(default_factory=list, max_length=40)

    @field_validator(
        "slug",
        "title",
        "excerpt",
        "category_id",
        "cover_image",
        "cover_alt",
        "author",
        "author_role",
        "published_at",
        "read_time",
        mode="before",
    )
    @classmethod
    def _clean(cls, value: object) -> object:
        cleaned = _strip(value)
        if isinstance(cleaned, str):
            return cleaned
        return value

    @field_validator("slug", mode="after")
    @classmethod
    def _lower_slug(cls, value: str) -> str:
        return value.lower()

    @field_validator("tags", "related_product_slugs", mode="before")
    @classmethod
    def _strings(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    @field_validator("related_product_slugs", mode="after")
    @classmethod
    def _product_slugs(cls, value: list[str]) -> list[str]:
        return [item.lower() for item in value]


class PostReorder(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=50)


def slug_ok(value: str) -> bool:
    return _SLUG.fullmatch(value) is not None
