"""Operational commands.

python -m app.cli migrate                 # alembic upgrade head
python -m app.cli seed [--company NAME]   # roles, currencies, categories, company settings
python -m app.cli create-admin --email E --name N   (password from ERP_ADMIN_PASSWORD or prompt)
python -m app.cli demo                    # demo users for each role (development only)
"""

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import import_all_models

API_DIR = Path(__file__).resolve().parent.parent

DEMO_PASSWORD = "Demo-Pass-2026"
DEMO_USERS = [
    ("finance@example.com", "Fiona Finance", "finance_manager"),
    ("pm@example.com", "Peter Project", "project_manager"),
    ("alice@example.com", "Alice Developer", "employee"),
    ("bob@example.com", "Bob Developer", "employee"),
]


def _run(coro: Coroutine[Any, Any, Any]) -> None:
    async def wrapper() -> None:
        try:
            await coro
        finally:
            await engine.dispose()  # pooled connections must close before the event loop does

    asyncio.run(wrapper())


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(cfg, "head")


async def seed(company: str) -> None:
    from app.modules.categories import api as categories
    from app.modules.rbac import api as rbac
    from app.modules.settings import api as settings

    async with SessionLocal() as session:
        await rbac.seed_default_roles(session)
        await settings.seed(session, company_name=company)
        created = await categories.seed(session)
        await session.commit()
    print(f"seeded (new system categories: {created})")


async def create_user(email: str, name: str, password: str, role_key: str) -> bool:
    from app.modules.auth import api as auth
    from app.modules.rbac import api as rbac

    async with SessionLocal() as session:
        if await auth.get_user_by_email(session, email):
            print(f"user {email} already exists; skipped")
            return False
        role = await rbac.role_by_key(session, role_key)
        await auth.create_user(
            session, actor_id=None, email=email, full_name=name, password=password, role_ids=[role.id]
        )
        await session.commit()
    print(f"created {role_key} {email}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    p_seed = sub.add_parser("seed")
    p_seed.add_argument("--company", default="My Company")
    p_admin = sub.add_parser("create-admin")
    p_admin.add_argument("--email", required=True)
    p_admin.add_argument("--name", default="Administrator")
    sub.add_parser("demo")
    args = parser.parse_args(argv)

    import_all_models()
    if args.cmd == "migrate":
        migrate()
    elif args.cmd == "seed":
        _run(seed(args.company))
    elif args.cmd == "create-admin":
        password = os.environ.get("ERP_ADMIN_PASSWORD") or getpass.getpass("Password: ")
        _run(create_user(args.email, args.name, password, "admin"))
    elif args.cmd == "demo":
        if get_settings().env == "prod":
            print("refusing to create demo users in prod", file=sys.stderr)
            return 1

        async def _demo() -> None:
            for email, name, role in DEMO_USERS:
                await create_user(email, name, DEMO_PASSWORD, role)

        _run(_demo())
        print(f"demo password for all demo users: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
