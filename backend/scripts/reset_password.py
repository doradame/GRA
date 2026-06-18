#!/usr/bin/env python3
"""Resetta la password di un utente dato email e nuova password.

Esempio:
    PYTHONPATH=/app python scripts/reset_password.py user@example.com nuova_password
"""

import argparse
import asyncio
import sys

import bcrypt
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.models.models import User
from app.core.config import get_settings


settings = get_settings()


async def reset_password(email: str, password: str) -> bool:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            print(f"Utente non trovato: {email}", file=sys.stderr)
            return False
        user.hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        await session.commit()
        print(f"Password aggiornata per: {email}")
    await engine.dispose()
    return True


def main():
    parser = argparse.ArgumentParser(description="Resetta la password di un utente.")
    parser.add_argument("email", help="Email dell'utente")
    parser.add_argument("password", help="Nuova password in chiaro")
    args = parser.parse_args()

    ok = asyncio.run(reset_password(args.email, args.password))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
