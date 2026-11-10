"""Suppliers, purchases, and the insert-only stock ledger.

Stock on hand stays on `products.quantity` or `product_variants.quantity`.
These tables record how that number moved. `stock_movements` is append-only:
the service never updates or deletes a row. On PostgreSQL a trigger rejects
DELETE and any change except nulling a foreign key when the parent row is
removed. Corrections are new movements.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    event,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MovementType(StrEnum):
    OPENING = "opening"
    PURCHASE = "purchase"
    SALE = "sale"
    RETURN = "return"
    CANCEL = "cancel"
    ADJUSTMENT = "adjustment"


class ImportKind(StrEnum):
    PURCHASES = "purchases"
    OPENING = "opening"
    STOCK_COUNT = "stock_count"
    COST_PRICE = "cost_price"


_MOVEMENT_SQL = ", ".join(f"'{item.value}'" for item in MovementType)
_IMPORT_SQL = ", ".join(f"'{item.value}'" for item in ImportKind)


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person or company the shop buys from."""

    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    address: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", server_default=""
    )
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<Supplier {self.name}>"


class ImportBatch(UUIDPrimaryKeyMixin, Base):
    """One confirmed spreadsheet upload. The hash detects the same file again."""

    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(f"import_type IN ({_IMPORT_SQL})", name="type_known"),
        Index("ix_import_batches_file_hash", "file_hash"),
    )

    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    import_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_name: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Purchase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Goods received from a supplier. Lines live on `purchase_items`."""

    __tablename__ = "purchases"
    __table_args__ = (Index("ix_purchases_supplier_date", "supplier_id", "purchased_on"),)

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    purchased_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    invoice_no: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )

    items: Mapped[list["PurchaseItem"]] = relationship(
        back_populates="purchase",
        cascade="all, delete-orphan",
        order_by="PurchaseItem.created_at",
    )


class PurchaseItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "purchase_items"
    __table_args__ = (
        CheckConstraint(
            "quantity >= 1 AND quantity <= 1000000",
            name="quantity_in_range",
        ),
        CheckConstraint("unit_cost >= 0", name="unit_cost_non_negative"),
    )

    purchase_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL so deleting a product (already allowed) does not erase the purchase line.
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    purchase: Mapped[Purchase] = relationship(back_populates="items")


class StockMovement(UUIDPrimaryKeyMixin, Base):
    """One stock change. Rows are inserted and then left alone.

    `quantity` is signed: purchases, opening stock, cancels and returns are
    positive; sales are negative; an adjustment is the difference. A cost-only
    import uses 0 and does not change the on-hand count.
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(f"movement_type IN ({_MOVEMENT_SQL})", name="type_known"),
        CheckConstraint(
            "quantity >= -1000000 AND quantity <= 1000000",
            name="quantity_bounds",
        ),
        CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0",
            name="unit_cost_non_negative",
        ),
        CheckConstraint(
            "(CASE WHEN order_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN purchase_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN import_batch_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
            name="one_source",
        ),
        Index("ix_stock_movements_created_at", "created_at"),
        Index(
            "uq_stock_movements_opening_product",
            "product_id",
            unique=True,
            postgresql_where=text("movement_type = 'opening' AND variant_id IS NULL"),
            sqlite_where=text("movement_type = 'opening' AND variant_id IS NULL"),
        ),
        Index(
            "uq_stock_movements_opening_variant",
            "variant_id",
            unique=True,
            postgresql_where=text("movement_type = 'opening' AND variant_id IS NOT NULL"),
            sqlite_where=text("movement_type = 'opening' AND variant_id IS NOT NULL"),
        ),
    )

    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    movement_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("purchases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    note: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def _reject_stock_movement_change(mapper: object, connection: object, target: object) -> None:
    """ORM updates and deletes never land. PostgreSQL also has a trigger."""
    del mapper, connection, target
    raise RuntimeError("stock_movements cannot be updated or deleted")


event.listen(StockMovement, "before_update", _reject_stock_movement_change)
event.listen(StockMovement, "before_delete", _reject_stock_movement_change)
