"""Test data builders that go through the public module facades (same rules as the API)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.core.db import SessionLocal
from app.modules.accounting import api as accounting
from app.modules.categories import api as categories
from app.modules.employees import api as employees
from app.modules.parties import api as parties
from app.modules.payments.models import PaymentAccount
from app.modules.projects import api as projects
from app.modules.projects import service as project_service

D = Decimal


async def category_id(group: str, key: str) -> str:
    async with SessionLocal() as s:
        return str((await categories.by_system_key(s, group, key)).id)


async def account_id(code: str) -> str:
    async with SessionLocal() as s:
        account = await accounting.account_by_code(s, code)
        assert account is not None, code
        return str(account.id)


async def payment_account_id(name: str) -> str:
    from sqlalchemy import select

    async with SessionLocal() as s:
        return str((await s.execute(select(PaymentAccount.id).where(PaymentAccount.name == name))).scalar_one())


async def customer(name: str = "Customer ABC", kind: str = "customer") -> str:
    async with SessionLocal() as s:
        party = await parties.create(s, actor_id=None, kind=kind, data={"name": name})
        await s.commit()
        return str(party.id)


async def employee(
    name: str, *, start: date = date(2026, 1, 1), user_id: str | None = None, email: str | None = None
) -> str:
    async with SessionLocal() as s:
        etype = await categories.by_system_key(s, "employment_type", "full_time")
        e = await employees.create(
            s,
            actor_id=None,
            data={
                "full_name": name,
                "employment_type_category_id": etype.id,
                "start_date": start,
                "status": "active",
                "user_id": uuid.UUID(user_id) if user_id else None,
                "email": email,
            },
        )
        await s.commit()
        return str(e.id)


async def project(
    name: str,
    customer_id: str | None,
    members: list[tuple[str, Decimal | None]],
    manager_id: str | None = None,
    ptype: str = "web_development",
) -> str:
    async with SessionLocal() as s:
        pt = await categories.by_system_key(s, "project_type", ptype)
        p = await projects.create(
            s,
            actor_id=None,
            data={
                "name": name,
                "customer_party_id": uuid.UUID(customer_id) if customer_id else None,
                "project_type_category_id": pt.id,
                "contract_value": D(10000),
                "status": "active",
                "manager_employee_id": uuid.UUID(manager_id) if manager_id else None,
            },
        )
        await project_service.set_members(
            s,
            actor_id=None,
            project_id=p.id,  # type: ignore[arg-type]
            rows=[{"employee_id": uuid.UUID(e), "default_allocation_pct": pct} for e, pct in members],
        )
        await s.commit()
        return str(p.id)


async def receipt_body(**overrides: Any) -> dict[str, Any]:
    """A customer project payment into Company Checking by bank transfer."""
    body = {
        "posting_date": "2026-11-10",
        "direction": "receive",
        "method_category_id": await category_id("payment_method", "bank_transfer"),
        "purpose_category_id": await category_id("payment_purpose", "project_payment"),
        "paid_to_payment_account_id": await payment_account_id("Company Checking"),
        "amount": "10000.00",
    }
    body.update(overrides)
    return body
