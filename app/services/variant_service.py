"""Product variants: validation, saving, the product roll-up, and purchase rules.

A variant is one combination of a product's option values (`content.options`) with its own
price and stock. Products without variants are untouched and keep price and stock on the
product row. For a variant product the product row holds a roll-up (lowest active price,
summed stock) so list sorting, price filters and dashboards keep reading one column.
"""

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, UnprocessableError
from app.models.product import Product, ProductVariant, StockStatus
from app.schemas.product import (
    ProductContent,
    PublicVariant,
    SelectedOption,
    VariantInput,
    VariantRead,
)

PLATFORM_MAX_QTY = 5


def option_key(options: dict[str, str]) -> str:
    """Canonical string for an option combination, independent of key order."""
    return "|".join(f"{group}={value}" for group, value in sorted(options.items()))


def selection_of_variant(content: ProductContent, options: dict[str, str]) -> list[SelectedOption]:
    """Label snapshot (group name, value label, swatch) for a variant, in group order."""
    chosen: list[SelectedOption] = []
    for group in content.options:
        value = next((item for item in group.values if item.id == options.get(group.id)), None)
        if value is not None:
            chosen.append(SelectedOption(name=group.name, label=value.label, swatch=value.swatch))
    return chosen


def label_of(content: ProductContent, options: dict[str, str]) -> str:
    return " / ".join(item.label for item in selection_of_variant(content, options))


def order_limits(product: Product) -> tuple[int, int]:
    """(minimum, maximum) quantity per order for a product, inside the platform cap."""
    maximum = min(PLATFORM_MAX_QTY, product.max_order_quantity or PLATFORM_MAX_QTY)
    return min(product.min_order_quantity, maximum), maximum


def stock_cap(product: Product, variant: ProductVariant | None) -> int:
    """Most units a shopper may take right now (min/max rule and live stock)."""
    _minimum, maximum = order_limits(product)
    stock = variant.quantity if variant is not None else product.quantity
    return maximum if stock is None else max(0, min(maximum, stock))


def variant_available(variant: ProductVariant, product: Product) -> bool:
    return variant.is_active and stock_cap(product, variant) >= order_limits(product)[0]


def check_combination(content: ProductContent, options: dict[str, str]) -> None:
    groups = [group for group in content.options if group.name and group.values]
    if set(options) != {group.id for group in groups}:
        raise UnprocessableError("Each variant needs one value for every option")
    for group in groups:
        if options[group.id] not in {value.id for value in group.values}:
            raise UnprocessableError(f"Choose a valid {group.name} for each variant")


def validate_inputs(content: ProductContent, variants: Sequence[VariantInput]) -> None:
    if variants and not [group for group in content.options if group.name and group.values]:
        raise UnprocessableError("Add option values (such as sizes or weights) before variants")
    seen_keys: set[str] = set()
    seen_skus: set[str] = set()
    seen_ids: set[uuid.UUID] = set()
    for item in variants:
        check_combination(content, item.options)
        key = option_key(item.options)
        if key in seen_keys:
            raise UnprocessableError("Two variants have the same option combination")
        seen_keys.add(key)
        if item.sku:
            folded = item.sku.casefold()
            if folded in seen_skus:
                raise UnprocessableError("Two variants have the same SKU")
            seen_skus.add(folded)
        if item.id is not None:
            if item.id in seen_ids:
                raise UnprocessableError("A variant was listed twice")
            seen_ids.add(item.id)


async def list_variants(db: AsyncSession, product_id: uuid.UUID) -> list[ProductVariant]:
    result = await db.execute(
        select(ProductVariant)
        .where(ProductVariant.product_id == product_id)
        .order_by(ProductVariant.sort_order, ProductVariant.created_at, ProductVariant.id)
    )
    return list(result.scalars().all())


async def ensure_still_valid(db: AsyncSession, product: Product, content: ProductContent) -> None:
    """Options may change on a variant product only if every variant still fits them."""
    if not product.has_variants:
        return
    for variant in await list_variants(db, product.id):
        try:
            check_combination(content, variant.options)
        except UnprocessableError:
            raise UnprocessableError(
                "An option used by a variant was removed or changed. Update the variants too."
            ) from None


async def save_variants(
    db: AsyncSession,
    product: Product,
    content: ProductContent,
    inputs: Sequence[VariantInput],
    *,
    explicit_status: bool,
) -> None:
    """Make the product's variants equal to `inputs` (matched by id), then roll up.

    Runs inside the caller's transaction. Variants not listed are deleted; carts holding them
    lose that line, past orders keep their own snapshot.
    """
    validate_inputs(content, inputs)
    existing = {variant.id: variant for variant in await list_variants(db, product.id)}
    for item in inputs:
        if item.id is not None and item.id not in existing:
            raise UnprocessableError("A variant does not belong to this product")
    await _check_sku_free(db, product.id, inputs)

    keep = {item.id for item in inputs if item.id is not None}
    for variant_id, variant in existing.items():
        if variant_id not in keep:
            await db.delete(variant)
    # Free every key and SKU that is about to change first, so swapping two variants'
    # options or SKUs never trips the unique indexes midway.
    changing = [
        existing[item.id]
        for item in inputs
        if item.id is not None
        and (
            existing[item.id].option_key != option_key(item.options)
            or existing[item.id].sku.casefold() != item.sku.casefold()
        )
    ]
    for variant in changing:
        variant.option_key = f"~{variant.id.hex}"
        variant.sku = ""
    await db.flush()

    for index, item in enumerate(inputs):
        row = existing[item.id] if item.id is not None else ProductVariant(product_id=product.id)
        row.options = dict(item.options)
        row.option_key = option_key(item.options)
        row.sku = item.sku
        row.price = item.price
        row.compare_at_price = item.compare_at_price
        row.quantity = item.quantity
        row.is_active = item.is_active
        row.sort_order = index
        if item.id is None:
            db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError("A variant SKU or option combination is already in use") from exc
    await rollup(db, product, explicit_status=explicit_status)


async def _check_sku_free(
    db: AsyncSession, product_id: uuid.UUID, inputs: Iterable[VariantInput]
) -> None:
    skus = {item.sku.casefold() for item in inputs if item.sku}
    if not skus:
        return
    result = await db.execute(
        select(ProductVariant.sku, ProductVariant.id)
        .where(func.lower(ProductVariant.sku).in_(skus), ProductVariant.product_id != product_id)
        .limit(1)
    )
    if result.first() is not None:
        raise ConflictError("A variant SKU is already used by another product")


async def rollup(db: AsyncSession, product: Product, *, explicit_status: bool = False) -> None:
    """Refresh the product row from its variants. Locks the product row first."""
    await db.execute(select(Product.id).where(Product.id == product.id).with_for_update())
    rows = await list_variants(db, product.id)
    if not rows:
        product.has_variants = False
        return
    active = [row for row in rows if row.is_active]
    basis = active or rows
    cheapest = min(basis, key=lambda row: (row.price, row.sort_order))
    product.has_variants = True
    product.price = cheapest.price
    product.compare_at_price = cheapest.compare_at_price
    if not active:
        product.quantity = 0
    elif any(row.quantity is None for row in active):
        product.quantity = None
    else:
        product.quantity = sum(row.quantity or 0 for row in active)
    if product.quantity == 0 and product.status == StockStatus.AVAILABLE.value:
        product.status = StockStatus.SOLD_OUT.value
    elif (
        not explicit_status
        and product.quantity != 0
        and product.status == StockStatus.SOLD_OUT.value
    ):
        product.status = StockStatus.AVAILABLE.value


async def rollup_by_id(db: AsyncSession, product_id: uuid.UUID) -> None:
    """Roll-up for order claim and restock, where only the id is at hand."""
    product = await db.get(Product, product_id, populate_existing=True)
    if product is not None and product.has_variants:
        await rollup(db, product)


async def lock_product(db: AsyncSession, product_id: uuid.UUID) -> None:
    await db.execute(select(Product.id).where(Product.id == product_id).with_for_update())


async def release_stock(db: AsyncSession, variant_id: uuid.UUID, quantity: int) -> None:
    await db.execute(
        update(ProductVariant)
        .where(ProductVariant.id == variant_id, ProductVariant.quantity.is_not(None))
        .values(quantity=ProductVariant.quantity + quantity)
    )


def admin_read(content: ProductContent, rows: Sequence[ProductVariant]) -> list[VariantRead]:
    return [
        VariantRead(
            id=row.id,
            options=dict(row.options),
            label=label_of(content, row.options),
            sku=row.sku,
            price=row.price,
            compare_at_price=row.compare_at_price,
            quantity=row.quantity,
            is_active=row.is_active,
            sort_order=row.sort_order,
        )
        for row in rows
    ]


def public_read(
    product: Product, content: ProductContent, rows: Sequence[ProductVariant]
) -> list[PublicVariant]:
    return [
        PublicVariant(
            id=row.id,
            options=dict(row.options),
            label=label_of(content, row.options),
            price=row.price,
            compare_at_price=row.compare_at_price,
            available=variant_available(row, product),
        )
        for row in rows
        if row.is_active
    ]


async def resolve_for_purchase(
    db: AsyncSession, product: Product, variant_id: uuid.UUID | None
) -> ProductVariant | None:
    """The variant a cart or order line points at, checked against the product.

    A variant product needs a variant; a plain product refuses one. The row is read from the
    database here, so nothing the client sent can change the price.
    """
    if not product.has_variants:
        if variant_id is not None:
            raise UnprocessableError("This product has no variants")
        return None
    if variant_id is None:
        raise UnprocessableError("Choose an option before ordering")
    variant = await db.get(ProductVariant, variant_id)
    if variant is None or variant.product_id != product.id or not variant.is_active:
        raise UnprocessableError("That option is not available")
    return variant
