import re
import uuid
from datetime import datetime
from typing import Literal, Self
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.models.product import ProductBadge, ProductCategory, SpecGroup, StockStatus

_ROW_ID = re.compile(r"[a-z0-9-]{1,40}")
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_BIDI = dict.fromkeys(map(ord, "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"), None)

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
MAX_PRICE = 10_000_000
MAX_QUANTITY = 1_000_000

DEFAULT_STOCK_LABEL = "স্টকে আছে"
DEFAULT_QUALITY_TITLE = "কোয়ালিটি চেকড প্রোডাক্ট"
DEFAULT_QUALITY_BODY = (
    "প্রতিটি প্রোডাক্ট ডেলিভারির আগে পরীক্ষা করা হয়, যাতে আপনার হাতে পৌঁছায় সম্পূর্ণ কার্যকর একটি আইটেম।"
)

AdminSort = Literal[
    "catalog",
    "name-asc",
    "name-desc",
    "price-asc",
    "price-desc",
    "stock-asc",
    "stock-desc",
]
CatalogSort = Literal["popularity", "price-asc", "price-desc", "newest"]
CatalogView = Literal["featured", "latest", "new"]
Visibility = Literal["live", "hidden"]


def clean_line(value: str, max_length: int) -> str:
    text = "".join(ch for ch in value.replace("\x00", "").translate(_BIDI) if ch >= " ")
    text = " ".join(text.split())
    if len(text) > max_length:
        raise ValueError(f"Must be at most {max_length} characters")
    return text


def clean_block(value: str, max_length: int) -> str:
    text = value.replace("\x00", "").translate(_BIDI).replace("\r\n", "\n").replace("\r", "\n")
    kept = "".join(ch for ch in text if ch == "\n" or ch >= " ")
    collapsed = "\n".join(line.rstrip() for line in kept.split("\n")).strip()
    if len(collapsed) > max_length:
        raise ValueError(f"Must be at most {max_length} characters")
    return collapsed


def clean_media_ref(value: str) -> str:
    """Allow a site path or an https URL. Reject scripts, data URLs, and traversal."""
    text = value.strip().translate(_BIDI).replace("\x00", "")
    if not text:
        return ""
    if any(ch.isspace() for ch in text) or "\\" in text:
        raise ValueError("Image address is not allowed")
    if len(text) > 2048:
        raise ValueError("Image address is too long")

    decoded = unquote(unquote(text))
    lowered = decoded.lower()
    if lowered.startswith(("javascript:", "data:", "vbscript:", "file:", "blob:")):
        raise ValueError("Image address is not allowed")
    if ".." in decoded.split("/"):
        raise ValueError("Image address is not allowed")

    if text.startswith("/"):
        if text.startswith("//"):
            raise ValueError("Image address is not allowed")
        return text

    parsed = urlsplit(text)
    host = (parsed.hostname or "").lower()
    local = host in {"localhost", "127.0.0.1"}
    if parsed.scheme == "https" or (parsed.scheme == "http" and local):
        if parsed.username or parsed.password or not host:
            raise ValueError("Image address is not allowed")
        return text
    raise ValueError("Image address must be a site path or an https URL")


def _row_id(prefix: str, value: object) -> str:
    if isinstance(value, str) and _ROW_ID.fullmatch(value):
        return value
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _lines(items: list[str], max_length: int) -> list[str]:
    cleaned: list[str] = []
    for item in items:
        text = clean_line(item, max_length)
        if text:
            cleaned.append(text)
    return cleaned


class GalleryImage(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    id: str = ""
    src: str = ""
    alt: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, value: object) -> str:
        return _row_id("gallery", value)

    @field_validator("src")
    @classmethod
    def _src(cls, value: str) -> str:
        return clean_media_ref(value)

    @field_validator("alt")
    @classmethod
    def _alt(cls, value: str) -> str:
        return clean_line(value, 300)


class SpecRow(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    id: str = ""
    label: str = ""
    value: str = ""
    group: SpecGroup = SpecGroup.GENERAL

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, value: object) -> str:
        return _row_id("spec", value)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return clean_line(value, 80)

    @field_validator("value")
    @classmethod
    def _value(cls, value: str) -> str:
        return clean_line(value, 240)


_SWATCH = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")
OptionKind = Literal["color", "size", "text"]


class OptionChoice(BaseModel):
    """The value a customer picked. The server looks up the label."""

    model_config = ConfigDict(extra="forbid")

    group_id: str = Field(min_length=1, max_length=40)
    value_id: str = Field(min_length=1, max_length=40)


class SelectedOption(BaseModel):
    name: str
    label: str
    swatch: str = ""


class OptionValue(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    id: str = ""
    label: str = ""
    swatch: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, value: object) -> str:
        return _row_id("value", value)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        return clean_line(value, 40)

    @field_validator("swatch")
    @classmethod
    def _swatch(cls, value: str) -> str:
        text = value.strip()
        if not text:
            return ""
        if not _SWATCH.fullmatch(text):
            raise ValueError("Color must be a hex color like #111827")
        return text.lower()


class ProductOption(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    id: str = ""
    name: str = ""
    kind: OptionKind = "text"
    values: list[OptionValue] = Field(default_factory=list, max_length=20)

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, value: object) -> str:
        return _row_id("option", value)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return clean_line(value, 40)


class FaqRow(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    id: str = ""
    question: str = ""
    answer: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def _id(cls, value: object) -> str:
        return _row_id("faq", value)

    @field_validator("question")
    @classmethod
    def _question(cls, value: str) -> str:
        return clean_line(value, 240)

    @field_validator("answer")
    @classmethod
    def _answer(cls, value: str) -> str:
        return clean_block(value, 2000)


class ProductContent(BaseModel):
    """Copy the product page renders. Price and stock status live on the product row."""

    model_config = ConfigDict(extra="forbid", validate_default=True)

    tagline: str = ""
    description: str = ""
    stock_label: str = DEFAULT_STOCK_LABEL
    unit_label: str = ""
    image_alt: str = ""
    quality_image_src: str = ""
    quality_image_alt: str = ""
    gallery: list[GalleryImage] = Field(default_factory=list, max_length=12)
    highlights: list[str] = Field(default_factory=list, max_length=30)
    suitable_for: list[str] = Field(default_factory=list, max_length=30)
    package_items: list[str] = Field(default_factory=list, max_length=30)
    how_to_use: list[str] = Field(default_factory=list, max_length=30)
    story_heading: str = ""
    story_body: str = ""
    story_bullets: list[str] = Field(default_factory=list, max_length=20)
    quality_title: str = DEFAULT_QUALITY_TITLE
    quality_body: str = DEFAULT_QUALITY_BODY
    specs: list[SpecRow] = Field(default_factory=list, max_length=40)
    faqs: list[FaqRow] = Field(default_factory=list, max_length=20)
    options: list[ProductOption] = Field(default_factory=list, max_length=6)

    @field_validator("tagline")
    @classmethod
    def _tagline(cls, value: str) -> str:
        return clean_line(value, 300)

    @field_validator("story_heading", "quality_title")
    @classmethod
    def _headings(cls, value: str) -> str:
        return clean_line(value, 200)

    @field_validator("stock_label")
    @classmethod
    def _stock_label(cls, value: str) -> str:
        return clean_line(value, 80)

    @field_validator("unit_label")
    @classmethod
    def _unit(cls, value: str) -> str:
        return clean_line(value, 40)

    @field_validator("image_alt", "quality_image_alt")
    @classmethod
    def _image_alt(cls, value: str) -> str:
        return clean_line(value, 300)

    @field_validator("quality_image_src")
    @classmethod
    def _quality_image(cls, value: str) -> str:
        return clean_media_ref(value)

    @field_validator("description", "story_body", "quality_body")
    @classmethod
    def _blocks(cls, value: str, info: ValidationInfo) -> str:
        limit = 2000 if info.field_name == "quality_body" else 8000
        return clean_block(value, limit)

    @field_validator("highlights", "suitable_for", "package_items", "how_to_use")
    @classmethod
    def _highlight_lines(cls, items: list[str]) -> list[str]:
        return _lines(items, 300)

    @field_validator("story_bullets")
    @classmethod
    def _bullets(cls, items: list[str]) -> list[str]:
        return _lines(items, 300)

    @field_validator("gallery")
    @classmethod
    def _gallery(cls, items: list[GalleryImage]) -> list[GalleryImage]:
        return [item for item in items if item.src]

    @field_validator("specs")
    @classmethod
    def _specs(cls, items: list[SpecRow]) -> list[SpecRow]:
        return [item for item in items if item.label and item.value]

    @field_validator("faqs")
    @classmethod
    def _faqs(cls, items: list[FaqRow]) -> list[FaqRow]:
        return [item for item in items if item.question and item.answer]

    @field_validator("options")
    @classmethod
    def _options(cls, items: list[ProductOption]) -> list[ProductOption]:
        kept: list[ProductOption] = []
        seen: set[str] = set()
        for item in items:
            values = [value for value in item.values if value.label]
            if not item.name or not values:
                continue
            key = item.name.casefold()
            if key in seen:
                raise ValueError("Option names must be different")
            seen.add(key)
            kept.append(item.model_copy(update={"values": values}))
        return kept


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    title: str
    subtitle: str = ""
    category: ProductCategory
    price: int = Field(ge=0, le=MAX_PRICE)
    compare_at_price: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    quantity: int | None = Field(default=None, ge=0, le=MAX_QUANTITY)
    status: StockStatus = StockStatus.AVAILABLE
    badge: ProductBadge | None = None
    image_src: str = ""
    featured: bool = False
    published: bool = False
    slug: str | None = None
    content: ProductContent = Field(default_factory=ProductContent)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        text = clean_line(value, 200)
        if not text:
            raise ValueError("Product name is required")
        return text

    @field_validator("subtitle")
    @classmethod
    def _subtitle(cls, value: str) -> str:
        return clean_line(value, 300)

    @field_validator("image_src")
    @classmethod
    def _image(cls, value: str) -> str:
        return clean_media_ref(value)

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        if not _SLUG.fullmatch(text) or len(text) > 160:
            raise ValueError("Slug must use lowercase letters, numbers, and hyphens")
        return text

    @model_validator(mode="after")
    def _prices(self) -> Self:
        if self.compare_at_price is not None and self.compare_at_price < self.price:
            raise ValueError("Compare-at price must be at least the selling price")
        return self


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    title: str | None = None
    subtitle: str | None = None
    category: ProductCategory | None = None
    price: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    compare_at_price: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    quantity: int | None = Field(default=None, ge=0, le=MAX_QUANTITY)
    status: StockStatus | None = None
    badge: ProductBadge | None = None
    image_src: str | None = None
    featured: bool | None = None
    published: bool | None = None
    content: ProductContent | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = clean_line(value, 200)
        if not text:
            raise ValueError("Product name is required")
        return text

    @field_validator("subtitle")
    @classmethod
    def _subtitle(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_line(value, 300)

    @field_validator("image_src")
    @classmethod
    def _image(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_media_ref(value)


class AdminProductCard(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    subtitle: str
    category: ProductCategory
    price: int
    compare_at_price: int | None
    quantity: int | None
    status: StockStatus
    badge: ProductBadge | None
    image_src: str
    featured: bool
    published: bool
    created_at: datetime


class AdminProductRead(AdminProductCard):
    content: ProductContent
    updated_at: datetime


class AdminProductMetrics(BaseModel):
    """Summary cards. Scoped to the category tab only."""

    total: int
    live: int
    hidden: int
    sold_out: int


class CategoryCounts(BaseModel):
    all: int
    gadgets: int
    fashion: int


class AdminProductList(BaseModel):
    items: list[AdminProductCard]
    total: int
    page: int
    page_size: int
    pages: int
    metrics: AdminProductMetrics
    category_counts: CategoryCounts


class PublicGalleryImage(BaseModel):
    src: str
    alt: str


class PublicSpec(BaseModel):
    label: str
    value: str
    group: SpecGroup


class PublicFaq(BaseModel):
    question: str
    answer: str


class PublicOptionValue(BaseModel):
    id: str
    label: str
    swatch: str


class PublicOptionGroup(BaseModel):
    id: str
    name: str
    kind: OptionKind
    values: list[PublicOptionValue]


class PublicProductCard(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    subtitle: str
    category: ProductCategory
    price: int
    compare_at_price: int | None
    unit_label: str
    image_src: str
    image_alt: str
    badge: ProductBadge | None
    status: StockStatus
    featured: bool


class PublicProductDetail(PublicProductCard):
    tagline: str
    description: str
    stock_label: str
    gallery: list[PublicGalleryImage]
    highlights: list[str]
    suitable_for: list[str]
    package_items: list[str]
    how_to_use: list[str]
    story_heading: str
    story_body: str
    story_bullets: list[str]
    quality_title: str
    quality_body: str
    quality_image_src: str
    quality_image_alt: str
    specs: list[PublicSpec]
    faqs: list[PublicFaq]
    options: list[PublicOptionGroup]
    related: list[PublicProductCard]


class PublicCategoryCounts(BaseModel):
    gadgets: int
    fashion: int


class AvailabilityCounts(BaseModel):
    available: int
    sold_out: int
    coming_soon: int


class PublicProductList(BaseModel):
    items: list[PublicProductCard]
    total: int
    page: int
    page_size: int
    pages: int
    category_counts: PublicCategoryCounts
    availability_counts: AvailabilityCounts


class AdminProductQuery(BaseModel):
    q: str | None = Field(default=None, max_length=80)
    category: ProductCategory | None = None
    status: StockStatus | None = None
    visibility: Visibility | None = None
    min_price: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    max_price: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    sort: AdminSort = "catalog"
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(10, ge=1, le=100)

    @field_validator("q")
    @classmethod
    def _q(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = " ".join(value.split())
        return text or None

    @model_validator(mode="after")
    def _price_range(self) -> Self:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price cannot be greater than max_price")
        return self

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class CatalogQuery(BaseModel):
    category: ProductCategory | None = None
    status: str | None = Field(default=None, max_length=80)
    badge: ProductBadge | None = None
    view: CatalogView | None = None
    min_price: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    max_price: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    sort: CatalogSort = "popularity"
    page: int = Field(1, ge=1, le=10_000)
    page_size: int = Field(8, ge=1, le=48)

    @field_validator("status")
    @classmethod
    def _status(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        allowed = {item.value for item in StockStatus}
        parts: list[str] = []
        for raw in value.split(","):
            item = raw.strip()
            if not item:
                continue
            if item not in allowed:
                raise ValueError("status must be available, sold-out, or coming-soon")
            if item not in parts:
                parts.append(item)
        return ",".join(parts) or None

    @model_validator(mode="after")
    def _price_range(self) -> Self:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price cannot be greater than max_price")
        return self

    @property
    def statuses(self) -> list[str]:
        if not self.status:
            return []
        return self.status.split(",")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
