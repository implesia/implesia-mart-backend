"""Load the live home-page banner when the table is still empty.

Usage:
    python -m scripts.seed_home_banner
"""

import asyncio

from app.db.session import SessionLocal
from app.services.home import banner_service


async def main() -> None:
    async with SessionLocal() as db:
        await banner_service.ensure_banner(db)
    print("Home banner ready.")


if __name__ == "__main__":
    asyncio.run(main())
