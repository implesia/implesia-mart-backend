import uuid

from sqlalchemy import (
    DDL,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import conv

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

LEGACY_SLUGS = ("gadgets", "fashion")
MAX_DEPTH = 6  # root = level 1; a product can sit at any level


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One node of the catalog tree (adjacency list).

    Parent links are validated in the service (no self, no descendant, depth limit) and
    guarded again in PostgreSQL by a trigger (see migration 0075), so a bad write cannot
    create a cycle even outside the API. Deleting a category that still has children or
    products is refused (ON DELETE RESTRICT on both foreign keys); the service offers an
    explicit `reassign_to` instead.
    """

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        Index(conv("ix_categories_parent_sort"), "parent_id", "sort_order"),
    )

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    image_src: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    meta_title: Mapped[str] = mapped_column(
        String(160), nullable=False, default="", server_default=""
    )
    meta_description: Mapped[str] = mapped_column(
        String(320), nullable=False, default="", server_default=""
    )

    def __repr__(self) -> str:
        return f"<Category {self.slug}>"


# The same guard migration 0075 installs, attached to the table so `create_all` (the
# integration test database) gets it too. Migration SQL is kept separately on purpose.
_CYCLE_FUNCTION = DDL(
    """
CREATE OR REPLACE FUNCTION categories_prevent_cycle() RETURNS trigger AS $$
BEGIN
    IF NEW.parent_id IS NULL THEN
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(7507501);
    IF EXISTS (
        WITH RECURSIVE up(id, parent_id, n) AS (
            SELECT id, parent_id, 1 FROM categories WHERE id = NEW.parent_id
            UNION ALL
            SELECT c.id, c.parent_id, up.n + 1
            FROM categories c JOIN up ON c.id = up.parent_id
            WHERE up.n < 64
        )
        SELECT 1 FROM up WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'category cycle: %% cannot sit under its own descendant', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
).execute_if(dialect="postgresql")
_CYCLE_TRIGGER = DDL(
    "CREATE TRIGGER categories_no_cycle BEFORE INSERT OR UPDATE OF parent_id "
    "ON categories FOR EACH ROW EXECUTE FUNCTION categories_prevent_cycle()"
).execute_if(dialect="postgresql")
event.listen(Category.__table__, "after_create", _CYCLE_FUNCTION)
event.listen(Category.__table__, "after_create", _CYCLE_TRIGGER)
