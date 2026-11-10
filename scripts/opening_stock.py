"""Record opening stock from the quantities already on the products.

Usage:
    python -m scripts.opening_stock

Creates one opening movement per product, or per variant when the product
tracks stock by option. The on-hand count is not changed. Running it again
does not add a second opening movement. Made-to-order rows (quantity NULL)
are skipped.

Run this once after migration 0093, on the application database, when orders
are quiet. It locks each product row while it reads the count.
"""

import asyncio

from app.db.session import SessionLocal
from app.services import inventory_service


async def main() -> None:
    async with SessionLocal() as db:
        result = await inventory_service.record_opening_stock(db, actor_id=None)
    print(
        "Opening stock: "
        f"{result.created} created, "
        f"{result.already_recorded} already recorded, "
        f"{result.untracked} made to order."
    )


if __name__ == "__main__":
    asyncio.run(main())
