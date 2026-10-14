"""point seeded CMS images at assets that ship with the storefront

Revision ID: 0070
Revises: 0069
Create Date: 2026-10-14

The original seed referenced /images/reviews/* and female-gorgious-ground-dress.jpeg,
which do not exist in the frontend public/ folder (QA IM-QA-002). Only rows still holding
the exact seeded path are changed, so admin-edited images are left alone.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GOWN_OLD = "/images/products/baby-products/female-gorgious-ground-dress.jpeg"
GOWN_NEW = "/images/products/baby-products/wedding-dress.jpeg"
REVIEWS = {
    "/images/reviews/sunset-lamp-1.jpg": "/images/products/lamp/lamp-1.jpg",
    "/images/reviews/sunset-lamp-2.jpg": "/images/products/lamp/lamp-2.jpg",
    "/images/reviews/phone-holder-1.jpg": "/images/products/car-holder/car-holder.jpg",
    "/images/reviews/phone-holder-2.jpg": "/images/products/selfie-stand/stand-1.jpg",
    "/images/reviews/gown-1.jpg": GOWN_NEW,
    "/images/reviews/baby-frock-1.jpg": "/images/products/baby-products/baby-frock.jpeg",
}
GOWN_TABLES = ("about_hero_images", "sustainability_hero_images", "about_dress_images")


def _swap(table: str, column: str, old: str, new: str) -> None:
    op.execute(
        sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old").bindparams(
            new=new, old=old
        )
    )


def upgrade() -> None:
    for table in GOWN_TABLES:
        _swap(table, "src", GOWN_OLD, GOWN_NEW)
    for old, new in REVIEWS.items():
        _swap("home_review_items", "image_src", old, new)


def downgrade() -> None:
    for table in GOWN_TABLES:
        _swap(table, "src", GOWN_NEW, GOWN_OLD)
    for old, new in REVIEWS.items():
        if new != GOWN_NEW:
            _swap("home_review_items", "image_src", new, old)
