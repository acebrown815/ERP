"""Operational commands.

python -m app.cli migrate [--seed]        # alembic upgrade head; --seed also adds what a release introduced
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
from app.core.errors import NotFound
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


async def seed_all(session: Any, company: str) -> dict[str, int]:
    """Idempotent: creates whatever is missing, never overwrites existing data."""
    from app.modules.accounting import api as accounting
    from app.modules.categories import api as categories
    from app.modules.compensation import api as compensation
    from app.modules.payments import api as payments
    from app.modules.rbac import api as rbac
    from app.modules.settings import api as settings

    await rbac.seed_default_roles(session)
    await settings.seed(session, company_name=company)
    created = {"categories": await categories.seed(session)}
    created["accounts"] = await accounting.seed(session)
    created["payment_accounts"] = await payments.seed_payment_accounts(session)
    await compensation.seed(session)
    return created


async def seed(company: str) -> None:
    async with SessionLocal() as session:
        created = await seed_all(session, company)
        await session.commit()
    print("seeded: " + ", ".join(f"{k} +{v}" for k, v in created.items()))


async def seed_existing() -> None:
    """Every deploy: add what a new release introduced. A first install is left alone, because seeding it by hand
    is what names the company, and a company created here would keep the default name."""
    from app.modules.settings import api as settings

    async with SessionLocal() as session:
        try:
            company = await settings.get_company(session)
        except NotFound:
            print("seed skipped: no company yet (first install: run `seed --company NAME`)")
            return
        created = await seed_all(session, company.name)
        await session.commit()
    print("seeded: " + ", ".join(f"{k} +{v}" for k, v in created.items()))


async def create_user(email: str, name: str, password: str, role_key: str) -> bool:
    from app.modules.auth import api as auth
    from app.modules.rbac import api as rbac

    async with SessionLocal() as session:
        if await auth.get_user_by_email(session, email):
            print(f"user {email} already exists; skipped")
            return False
        try:
            role = await rbac.role_by_key(session, role_key)
        except NotFound:
            raise SystemExit(f"role {role_key!r} not found; run `python -m app.cli seed --company ...` first") from None
        await auth.create_user(
            session, actor_id=None, email=email, full_name=name, password=password, role_ids=[role.id]
        )
        await session.commit()
    print(f"created {role_key} {email}")
    return True


async def demo_business() -> None:
    """Sample data matching the reference scenario (docs/architecture.md, Section 16). Skipped if present."""
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import select

    from app.modules.attribution import api as attribution
    from app.modules.auth import api as auth
    from app.modules.categories import api as categories
    from app.modules.employees import api as employees
    from app.modules.parties import api as parties
    from app.modules.payments import service as payments
    from app.modules.payments.models import PaymentAccount
    from app.modules.projects import api as projects
    from app.modules.projects import service as project_service

    async with SessionLocal() as s:
        if await parties.find_by_name(s, "customer", "Customer ABC"):
            print("demo business data already present; skipped")
            return
        admin = await auth.get_user_by_email(s, "admin@example.com")
        actor = admin.id if admin else None
        cat = lambda g, k: categories.by_system_key(s, g, k)  # noqa: E731
        full_time = await cat("employment_type", "full_time")
        abc = await parties.create(
            s, actor_id=actor, kind="customer", data={"name": "Customer ABC", "email": "ap@abc.example"}
        )
        await parties.create(s, actor_id=actor, kind="supplier", data={"name": "Cloud Hosting Inc."})
        team = []
        for name, email in (("Employee A", "alice@example.com"), ("Employee B", "bob@example.com")):
            user = await auth.get_user_by_email(s, email)
            team.append(
                await employees.create(
                    s,
                    actor_id=actor,
                    data={
                        "full_name": name,
                        "email": email,
                        "employment_type_category_id": full_time.id,
                        "start_date": date(date.today().year, 1, 1),
                        "status": "active",
                        "user_id": user.id if user else None,
                    },
                )
            )
        web = await cat("project_type", "web_development")
        project = await projects.create(
            s,
            actor_id=actor,
            data={
                "name": "ABC Web Platform",
                "customer_party_id": abc.id,
                "project_type_category_id": web.id,
                "contract_value": Decimal(10000),
                "status": "active",
                "start_date": date.today().replace(day=1),
            },
        )
        await project_service.set_members(
            s,
            actor_id=actor,
            project_id=project.id,
            rows=[
                {"employee_id": team[0].id, "default_allocation_pct": Decimal(60)},
                {"employee_id": team[1].id, "default_allocation_pct": Decimal(40)},
            ],
        )
        checking = (
            await s.execute(select(PaymentAccount).where(PaymentAccount.name == "Company Checking"))
        ).scalar_one()
        receipt = await payments.create_draft(
            s,
            actor_id=actor,
            splits=None,
            data={
                "posting_date": date.today(),
                "direction": "receive",
                "party_id": abc.id,
                "project_id": project.id,
                "method_category_id": (await cat("payment_method", "bank_transfer")).id,
                "purpose_category_id": (await cat("payment_purpose", "project_payment")).id,
                "paid_to_payment_account_id": checking.id,
                "amount": Decimal(10000),
                "exchange_rate": Decimal(1),
                "fee_amount": Decimal(0),
                "fee_paid_by": "company",
                "reference_no": "WIRE-0001",
                "description": "Milestone 1 payment",
            },
        )
        assert await attribution.for_payment(s, receipt.id)  # pre-filled 60/40 from the project
        await payments.submit(s, actor_id=actor, pe_id=receipt.id)
        expense = await payments.create_draft(
            s,
            actor_id=actor,
            splits=None,
            data={
                "posting_date": date.today(),
                "direction": "pay",
                "amount": Decimal("420.50"),
                "exchange_rate": Decimal(1),
                "fee_amount": Decimal(0),
                "fee_paid_by": "company",
                "paid_from_payment_account_id": checking.id,
                "method_category_id": (await cat("payment_method", "bank_transfer")).id,
                "purpose_category_id": (await cat("payment_purpose", "operating_expense")).id,
                "category_id": (await cat("expense_category", "cloud_infrastructure")).id,
                "description": "Monthly hosting",
            },
        )
        await payments.submit(s, actor_id=actor, pe_id=expense.id)
        await s.commit()
    print("created demo business data: Customer ABC, Employees A and B, project, receipt, expense")


async def demo_salary() -> None:
    """Put the demo employees on the default salary formula (idempotent)."""
    from app.modules.compensation import api as compensation
    from app.modules.employees import api as employees

    async with SessionLocal() as s:
        formula = await compensation.default_formula(s)
        assert formula is not None, "run seed first"
        added = 0
        for email in ("alice@example.com", "bob@example.com"):
            employee = await employees.find_by_email(s, email)
            if employee and not await compensation.list_assignments(s, employee_id=employee.id):
                await compensation.create_assignment(
                    s, actor_id=None, employee_id=employee.id, formula_id=formula.id, effective_from=employee.start_date
                )
                added += 1
        await s.commit()
    print(f"demo salary formula assignments: +{added}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_migrate = sub.add_parser("migrate")
    p_migrate.add_argument("--seed", action="store_true", help="then add what a release introduced, if already set up")
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
        if args.seed:
            _run(seed_existing())
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
            await demo_business()
            await demo_salary()

        _run(_demo())
        print(f"demo password for all demo users: {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
