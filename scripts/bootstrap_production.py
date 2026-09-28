"""Create the bootstrap admin when the API starts in production."""

import asyncio

from app.core.config import settings
from scripts.create_superuser import main as create_superuser


async def main() -> None:
    await create_superuser(
        settings.first_superuser_email,
        settings.first_superuser_password,
        "Implesia Mart Admin",
    )
    print("Production bootstrap complete.")


if __name__ == "__main__":
    asyncio.run(main())
