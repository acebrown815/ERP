"""Cross-module reports. Reads other modules' facades only; owns no tables."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.core.csv_export import csv_response
from app.core.db import get_session
from app.modules.accounting import api as accounting
from app.modules.attribution import api as attribution
from app.modules.auth.api import CurrentUser, require
from app.modules.projects import api as projects
from app.modules.rbac.api import Scope
from app.modules.salary import api as salary
from app.modules.settings import api as settings
from app.modules.tasks import api as tasks

router = APIRouter(tags=["reports"])

ZERO = Decimal(0)
Financials = Depends(require("projects.read_financials", Scope.PROJECT))


class ProjectFinancialsOut(BaseModel):
    """docs/architecture.md, Section 11.1. Amounts in the base currency."""

    project_id: uuid.UUID
    number: str
    name: str
    status: str
    customer_name: str | None
    base_currency: str
    contract_value: Decimal | None
    budget: Decimal | None
    revenue: Decimal  # income lines tagged with the project (cash basis: received = recognized)
    attributed_revenue: Decimal  # credited to employees (equals revenue when every receipt is split)
    direct_expenses: Decimal  # expense lines tagged with the project, excluding salaries
    salary_paid: Decimal  # salary expense lines tagged with the project
    salary_owed: Decimal  # earned on the project's revenue but not paid yet (management figure)
    profit_cash: Decimal  # revenue - direct expenses - salary paid
    profit_incl_owed: Decimal  # profit_cash - salary_owed
    margin_pct: Decimal | None
    budget_used: Decimal  # direct expenses + salary paid
    budget_remaining: Decimal | None
    contract_remaining: Decimal | None  # contract value not yet received
    completion_pct: Decimal  # manual override, else task-derived
    tasks_total: int
    tasks_done: int
    tasks_overdue: int
    estimate_hours: Decimal
    logged_hours: Decimal


async def _financials(
    session: AsyncSession, project_list: list[Any], date_from: date | None, date_to: date | None
) -> list[ProjectFinancialsOut]:
    ids = [p.id for p in project_list]
    base = (await settings.base_currency(session)).code
    ledger = await accounting.project_ledger(session, ids, date_from=date_from, date_to=date_to)
    credited = await attribution.project_totals(session, ids)
    pay = await salary.project_salary(session, ids)
    progress = await tasks.progress(session, ids, await settings.today(session))
    customers = await lookup.resolve(session, "party", (p.customer_party_id for p in project_list))
    out = []
    for p in project_list:
        led = ledger[p.id]
        earned, matched = pay.get(p.id, (ZERO, ZERO))
        owed = max(earned - matched, ZERO)
        profit = led.income - led.expenses - led.salary
        prog = progress.get(p.id)
        used = led.expenses + led.salary
        out.append(
            ProjectFinancialsOut(
                project_id=p.id,
                number=p.number,
                name=p.name,
                status=p.status,
                customer_name=customers.get(p.customer_party_id) if p.customer_party_id else None,
                base_currency=base,
                contract_value=p.contract_value,
                budget=p.budget,
                revenue=led.income,
                attributed_revenue=credited.get(p.id, ZERO),
                direct_expenses=led.expenses,
                salary_paid=led.salary,
                salary_owed=owed,
                profit_cash=profit,
                profit_incl_owed=profit - owed,
                margin_pct=(profit * 100 / led.income).quantize(Decimal("0.1")) if led.income > 0 else None,
                budget_used=used,
                budget_remaining=p.budget - used if p.budget is not None else None,
                contract_remaining=max(p.contract_value - led.income, ZERO) if p.contract_value is not None else None,
                completion_pct=p.completion_override
                if p.completion_override is not None
                else (prog.percent if prog else ZERO),
                tasks_total=prog.total if prog else 0,
                tasks_done=prog.done if prog else 0,
                tasks_overdue=prog.overdue if prog else 0,
                estimate_hours=prog.estimate_hours if prog else ZERO,
                logged_hours=prog.logged_hours if prog else ZERO,
            )
        )
    return out


@router.get("/projects/{project_id}/financials", response_model=ProjectFinancialsOut)
async def project_financials(
    project_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    user: CurrentUser = Financials,
    session: AsyncSession = Depends(get_session),
) -> ProjectFinancialsOut:
    project = await projects.get(session, project_id)
    await projects.ensure_visible(session, user, "projects.read_financials", project)
    out = (await _financials(session, [project], date_from, date_to))[0]
    await session.commit()  # salary periods may have been generated
    return out


@router.get("/reports/project-profitability", response_model=list[ProjectFinancialsOut])
async def project_profitability(
    status: Literal["planned", "active", "on_hold", "completed", "cancelled"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    format: Literal["json", "csv"] = "json",
    user: CurrentUser = Financials,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Every visible project's financials, most profitable first."""
    only = None
    if user.scope_for("projects.read_financials") != Scope.ALL:
        only = await projects.visible_project_ids(session, user)
    stmt = projects.list_stmt(q=None, status=status, customer_party_id=None, only_ids=only)
    rows = list((await session.execute(stmt.limit(500))).scalars())
    out = sorted(await _financials(session, rows, date_from, date_to), key=lambda r: -r.profit_cash)
    await session.commit()
    if format == "csv":
        fields = [
            "number",
            "name",
            "customer_name",
            "status",
            "contract_value",
            "budget",
            "revenue",
            "direct_expenses",
            "salary_paid",
            "salary_owed",
            "profit_cash",
            "profit_incl_owed",
            "margin_pct",
            "completion_pct",
            "logged_hours",
        ]
        return csv_response("project-profitability.csv", fields, ([getattr(r, f) for f in fields] for r in out))
    return out
