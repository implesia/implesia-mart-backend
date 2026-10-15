"""One optional photo per sustainability section (hero, point of view, quality, durability).

Unlike the About page, a sustainability section may have no photo at all: the storefront
then uses its text-only layout. When a photo is present it needs alt text.

``image`` is the canonical write field. ``images`` is still accepted so an admin build from
before this change keeps working during a deploy: the first active entry is used and the
rest are ignored.
"""

from pydantic import Field, field_validator, model_validator

from app.schemas.common import WriteModel

MISSING_ALT = "Add a short description of the photo (alt text)."


class OptionalImageWrite(WriteModel):
    alt: str = Field(default="", max_length=200)
    src: str = Field(default="", max_length=255)

    @field_validator("alt", "src", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class LegacyImageWrite(OptionalImageWrite):
    """Old multi-photo item shape (origin items also carried ``is_active``)."""

    is_active: bool = True


class OptionalImageMixin(WriteModel):
    image: OptionalImageWrite | None = None
    images: list[LegacyImageWrite] = Field(
        default_factory=list,
        max_length=12,
        description="Deprecated: use `image`. Only the first active entry is kept.",
    )

    @model_validator(mode="after")
    def _fold_legacy_images(self) -> "OptionalImageMixin":
        if self.image is None and self.images:
            first = next((item for item in self.images if item.is_active), None)
            if first is not None:
                self.image = OptionalImageWrite(src=first.src, alt=first.alt)
        self.images = []
        return self
