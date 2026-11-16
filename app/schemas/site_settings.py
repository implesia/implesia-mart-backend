from pydantic import BaseModel, field_validator

from app.schemas.common import WriteModel
from app.schemas.product import clean_line

# Home/default document title and meta description. The template is the
# pattern around a page title (`%s | Implesia Mart`), not the title itself.
SEO_TITLE_MAX = 70
SEO_DESCRIPTION_MAX = 170
SEO_TITLE_TEMPLATE_MAX = 80


def _empty_to_none(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    text = clean_line(value, max_length)
    return text or None


def _template(value: str | None) -> str | None:
    text = _empty_to_none(value, SEO_TITLE_TEMPLATE_MAX)
    if text is None:
        return None
    if text.count("%s") != 1 or "%" in text.replace("%s", "", 1):
        raise ValueError("Use %s once, for example %s | Implesia Mart")
    return text


class SiteSettingsRead(BaseModel):
    """Public and admin read. Null means the storefront uses its own default."""

    seo_title: str | None = None
    seo_description: str | None = None
    seo_title_template: str | None = None


class SiteSettingsUpdate(WriteModel):
    """Partial update. A field left out stays as it is. Null or blank clears it."""

    seo_title: str | None = None
    seo_description: str | None = None
    seo_title_template: str | None = None

    @field_validator("seo_title")
    @classmethod
    def _seo_title(cls, value: str | None) -> str | None:
        return _empty_to_none(value, SEO_TITLE_MAX)

    @field_validator("seo_description")
    @classmethod
    def _seo_description(cls, value: str | None) -> str | None:
        return _empty_to_none(value, SEO_DESCRIPTION_MAX)

    @field_validator("seo_title_template")
    @classmethod
    def _seo_title_template(cls, value: str | None) -> str | None:
        return _template(value)
