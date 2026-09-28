"""Create or promote the bootstrap superuser.

Usage:
    python -m scripts.create_superuser
    python -m scripts.create_superuser --email you@implesia.com --password '...'
"""

import argparse
import asyncio

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import UserRole
from app.schemas.user import UserCreate
from app.services import user_service


async def main(email: str, password: str, full_name: str) -> None:
    async with SessionLocal() as db:
        existing = await user_service.get_by_email(db, email)
        if existing is not None:
            existing.role = UserRole.SUPERADMIN
            existing.is_active = True
            await db.commit()
            print(f"Existing user {email} promoted to superadmin.")
            return

        await user_service.create_user(
            db,
            UserCreate(
                email=email,
                full_name=full_name,
                password=password,
                role=UserRole.SUPERADMIN,
            ),
        )
        print(f"Superuser {email} created.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=settings.first_superuser_email)
    parser.add_argument("--password", default=settings.first_superuser_password)
    parser.add_argument("--name", default="Implesia Mart Admin")
    args = parser.parse_args()

    asyncio.run(main(args.email, args.password, args.name))
