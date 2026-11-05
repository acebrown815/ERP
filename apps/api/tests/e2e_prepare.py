"""Browser tests (apps/web/e2e): rebuild their own database with the demo data. Run with `python -m tests.e2e_prepare`.

Everything in the database is deleted, so it refuses any database not named `*_e2e`.
"""

import asyncio
import os
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "Demo-Pass-2026"  # the same as the demo users; this database only exists for the tests


async def recreate(url: str) -> None:
    parsed = make_url(url)
    name = parsed.database or ""
    if not name.endswith("_e2e"):
        raise SystemExit(f"refusing to delete database {name!r}: its name must end in _e2e")
    engine = create_async_engine(parsed.set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


def cli(*args: str) -> None:
    env = {**os.environ, "ERP_ADMIN_PASSWORD": ADMIN_PASSWORD}
    subprocess.run([sys.executable, "-m", "app.cli", *args], check=True, env=env)


def main() -> None:
    asyncio.run(recreate(os.environ["ERP_DATABASE_URL"]))
    cli("migrate")
    cli("seed", "--company", "E2E Co")
    cli("create-admin", "--email", ADMIN_EMAIL, "--name", "Administrator")
    cli("demo")


if __name__ == "__main__":
    main()
