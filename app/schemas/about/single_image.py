"""One photo per About section (hero, story, custom dress).

The storefront shows a single image, so the admin edits exactly one. ``image`` is the
canonical field. ``images`` is still accepted on writes so an admin build from before
this change keeps working during a deploy: its first entry is used and the rest ignored.
"""

from pydantic import Field, field_validator, model_validator

from app.schemas.common import WriteModel


class SingleImageWrite(WriteModel):
    alt: str = Field(default="", max_length=200)
    src: str = Field(default="", max_length=255)

    @field_validator("alt", "src")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class SingleImageMixin(WriteModel):
    image: SingleImageWrite | None = None
    images: list[SingleImageWrite] = Field(
        default_factory=list,
        max_length=12,
        description="Deprecated: use `image`. Only the first entry is kept.",
    )

    @model_validator(mode="after")
    def _fold_legacy_images(self) -> "SingleImageMixin":
        if self.image is None and self.images:
            self.image = self.images[0]
        self.images = []
        return self


MISSING_PHOTO = "Add a photo for this section."
MISSING_ALT = "Add a short description of the photo (alt text)."
