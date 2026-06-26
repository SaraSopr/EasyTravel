"""Create a dev user in the database.

Usage:
    python create_dev_user.py <email> <password>

Example:
    python create_dev_user.py dev@easytravel.local password123
"""
import asyncio
import sys
import uuid

from app.database import AsyncSessionLocal
from app.models.user import User
from app.utils.auth import hash_password


async def main(email: str, password: str) -> None:
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            print(f"User {email} already exists.")
            return

        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=hash_password(password),
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        print(f"Created user: {email}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python create_dev_user.py <email> <password>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
