"""Cross-module reports. Reads other modules' facades only; owns no tables."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.core.db import get_session
from app.core.errors import Forbidden, NotFound, ValidationFailed, field_error
from app.core.exports import Format, export_response
from app.modules.accounting import api as accounting
from app.modules.attribution import api as attribution
from app.modules.auth.api import CurrentUser, current_user, require, require_any
from app.modules.categories import api as categories
from app.modules.employees import api as employees
from app.modules.payments import api as payments
from app.modules.projects import api as projects
from app.modules.rbac.api import Scope
from app.modules.reporting.periods import PeriodCol, bucketer, pct, recent_periods
from app.modules.salary import api as salary
from app.modules.settings import api as settings
from app.modules.tasks import api as tasks

router = APIRouter(tags=["reports"])

ZERO = Decimal(0)
Financials = Depends(require("projects.read_financials", Scope.ALL))


class ProjectFinancialsOut(BaseModel):
    """docs/architecture.md, Section 11.1. Amounts in the base currency."""

    project_id: uuid.UUID
    number: str
    name: str
    status: str
    lapsed: bool = False  # active, but no income in the last 3 months
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
    hours_used_pct: Decimal | None = None  # logged / estimated
    revenue_per_hour: Decimal | None = None  # revenue / logged hours


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
    lapsed = await projects.lapsed_ids(session, project_list)
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
                lapsed=p.id in lapsed,
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
                hours_used_pct=pct(prog.logged_hours, prog.estimate_hours) if prog else None,
                revenue_per_hour=(led.income / prog.logged_hours).quantize(Decimal("0.01"))
                if prog and prog.logged_hours > 0
                else None,
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
    format: Format = "json",
    user: CurrentUser = Financials,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Every project's financials, most profitable first."""
    stmt = projects.list_stmt(q=None, status=status, customer_party_id=None, only_ids=None)
    rows = list((await session.execute(stmt.limit(500))).scalars())
    out = sorted(await _financials(session, rows, date_from, date_to), key=lambda r: -r.profit_cash)
    await session.commit()
    if format != "json":
        fields = [
            "number",
            "name",
            "customer_name",
            "status",
            "lapsed",
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
            "revenue_per_hour",
        ]
        return export_response(format, "project-profitability", fields, ([getattr(r, f) for f in fields] for r in out))
    return out


class MyProjectRow(BaseModel):
    project_id: uuid.UUID
    received: Decimal  # receipts on the project credited to them (their share)
    paid: Decimal  # payments on the project to them or for them (salary, expenses tagged or shared: their share)
    net: Decimal  # received - paid
    payments: int
    base_currency: str


@router.get("/reports/my-project-contribution", response_model=list[MyProjectRow])
async def my_project_contribution(
    user: CurrentUser = Depends(require_any("salary.read", "revenue.read")),
    session: AsyncSession = Depends(get_session),
) -> list[MyProjectRow]:
    """The signed-in employee's payments per project, summed as they see them in Payment Entries (employees
    don't see project totals)."""
    own = await employees.for_user(session, user.id)
    if own is None:
        raise NotFound("Your user is not linked to an employee record")
    totals = await payments.employee_project_totals(session, employee_id=own.id, employee_party_id=own.party_id)
    base = (await settings.base_currency(session)).code
    return [
        MyProjectRow(project_id=p, received=received, paid=paid, net=received - paid, payments=n, base_currency=base)
        for p, (received, paid, n) in totals.items()
    ]


# ---- income / expense by category ------------------------------------------------------------------


class CategoryRow(BaseModel):
    account_code: str
    account_name: str
    category_id: uuid.UUID | None
    category_name: str | None
    amount: Decimal
    lines: int
    share_pct: Decimal


class CategoryReportOut(BaseModel):
    kind: str
    date_from: date
    date_to: date
    base_currency: str
    rows: list[CategoryRow]
    total: Decimal


Report = Depends(require("reports.financial"))


@router.get("/reports/by-category", response_model=CategoryReportOut)
async def by_category(
    kind: Literal["income", "expense"],
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    format: Format = "json",
    _: CurrentUser = Report,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Income or expenses per account and category (what the payment was classified as)."""
    rows = await accounting.category_totals(session, root_type=kind, date_from=date_from, date_to=date_to)
    names = {}
    for cid in {r.category_id for r in rows if r.category_id}:
        names[cid] = (await categories.get(session, cid)).name
    total = sum((r.amount for r in rows), ZERO)
    out = [
        CategoryRow(
            account_code=r.code,
            account_name=r.name,
            category_id=r.category_id,
            category_name=names.get(r.category_id) if r.category_id else None,
            amount=r.amount,
            lines=r.lines,
            share_pct=(r.amount * 100 / total).quantize(Decimal("0.1")) if total else ZERO,
        )
        for r in sorted(rows, key=lambda r: -r.amount)
    ]
    if format != "json":
        title = ("Income" if kind == "income" else "Expenses") + f" by category, {date_from} to {date_to}"
        return export_response(
            format,
            f"{kind}-by-category_{date_from}_{date_to}",
            ["account", "category", "amount", "share %", "lines"],
            [
                *(
                    [f"{r.account_code} {r.account_name}", r.category_name or "-", r.amount, r.share_pct, r.lines]
                    for r in out
                ),
                ["Total", "", total, Decimal(100) if total else ZERO, sum(r.lines for r in out)],
            ],
            title=title,
        )
    base = (await settings.base_currency(session)).code
    return CategoryReportOut(kind=kind, date_from=date_from, date_to=date_to, base_currency=base, rows=out, total=total)


# ---- customer / supplier payments ------------------------------------------------------------------


class PartyRow(BaseModel):
    party_id: uuid.UUID | None
    party_name: str
    payments: int
    total: Decimal
    last_payment: date | None
    share_pct: Decimal


class PartyReportOut(BaseModel):
    direction: str
    date_from: date
    date_to: date
    base_currency: str
    rows: list[PartyRow]
    total: Decimal


@router.get("/reports/party-payments", response_model=PartyReportOut)
async def party_payments(
    direction: Literal["receive", "pay"],
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    format: Format = "json",
    _: CurrentUser = Report,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Money received per customer (receive) or paid per supplier / payee (pay), in the base currency."""
    rows = await payments.party_totals_between(session, direction=direction, date_from=date_from, date_to=date_to)
    names = await lookup.resolve(session, "party", (p for p, *_ in rows))
    total = sum((t for _, _, t, _ in rows), ZERO)
    no_party = "No party (transfers, owner)" if direction == "pay" else "No party"
    out = sorted(
        (
            PartyRow(
                party_id=p,
                party_name=names.get(p, "?") if p else no_party,
                payments=n,
                total=t,
                last_payment=last,
                share_pct=(t * 100 / total).quantize(Decimal("0.1")) if total else ZERO,
            )
            for p, n, t, last in rows
        ),
        key=lambda r: -r.total,
    )
    label = "customer-payments" if direction == "receive" else "supplier-payments"
    if format != "json":
        who = "Customer" if direction == "receive" else "Supplier"
        return export_response(
            format,
            f"{label}_{date_from}_{date_to}",
            ["party", "payments", "total", "share %", "last payment"],
            [
                *([r.party_name, r.payments, r.total, r.share_pct, r.last_payment] for r in out),
                ["Total", sum(r.payments for r in out), total, "", ""],
            ],
            title=f"{who} payments, {date_from} to {date_to}",
        )
    base = (await settings.base_currency(session)).code
    return PartyReportOut(
        direction=direction, date_from=date_from, date_to=date_to, base_currency=base, rows=out, total=total
    )


# ---- hired managers --------------------------------------------------------------------------------

HIRE_STALE_DAYS = 7  # no activity for this long gets flagged on the report


class HiredManagerRow(BaseModel):
    hire_id: uuid.UUID
    hire_name: str
    hire_status: str
    manager_id: uuid.UUID | None  # empty for a hire who has no project or payment yet
    manager_name: str | None
    projects: int = 0
    tasks_created: int = 0
    tasks_completed: int = 0
    tasks_open: int = 0
    tasks_overdue: int = 0
    last_activity: datetime | None = None
    stale: bool = False
    paid: Decimal = ZERO
    manager_gross_revenue: Decimal = ZERO
    manager_net_revenue: Decimal = ZERO


class HiredManagersOut(BaseModel):
    date_from: date
    date_to: date
    base_currency: str
    stale_after_days: int
    rows: list[HiredManagerRow]


@router.get("/reports/hired-managers", response_model=HiredManagersOut)
async def hired_managers(
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    format: Format = "json",
    user: CurrentUser = Depends(require("hired_managers.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """One row per hire and project manager. Each figure counts only that manager's projects, so a manager
    never sees what a shared hire does or earns for anyone else."""
    own = await employees.for_user(session, user.id)
    if user.restricted:
        raise Forbidden("This report isn't available with restricted access")
    everyone = user.scope_for("hired_managers.read") == Scope.ALL
    if not everyone and own is None:
        raise NotFound("Your user is not linked to an employee record")

    today = await settings.today(session)
    hires = {h.id: h for h in await employees.all_hires(session)}
    by_party = {h.party_id: h for h in hires.values()}
    paid = await payments.hire_paid_totals(session, party_ids=list(by_party), date_from=date_from, date_to=date_to)
    on_projects: dict[tuple[uuid.UUID, uuid.UUID | None], list[projects.Project]] = {}
    for p in await projects.with_hires(session):
        if p.hire_employee_id in hires:
            on_projects.setdefault((p.hire_employee_id, p.manager_employee_id), []).append(p)

    pairs = {*on_projects, *((by_party[party].id, manager) for party, manager in paid)}
    if everyone:
        pairs |= {(h, None) for h in hires if not any(pair[0] == h for pair in pairs)}
    else:
        pairs = {pair for pair in pairs if own is not None and pair[1] == own.id}

    project_ids = [p.id for rows in on_projects.values() for p in rows]
    activity = await tasks.activity(session, project_ids, date_from=date_from, date_to=date_to, today=today)
    managers = list({m for _, m in pairs if m})
    names = await employees.names(session, managers)
    span: dict[str, Any] = {"date_from": date_from, "date_to": date_to, "employee_ids": managers}
    gross = await attribution.employee_totals(session, **span) if managers else {}
    spent = await salary.expense_totals(session, **span) if managers else {}

    rows: list[HiredManagerRow] = []
    for hire_id, manager_id in pairs:
        hire = hires[hire_id]
        mine = on_projects.get((hire_id, manager_id), [])
        row = HiredManagerRow(
            hire_id=hire_id,
            hire_name=hire.full_name,
            hire_status=hire.status,
            manager_id=manager_id,
            manager_name=names.get(manager_id) if manager_id else None,
            projects=len(mine),
            paid=paid.get((hire.party_id, manager_id), ZERO) if manager_id else ZERO,
            manager_gross_revenue=(gross.get(manager_id) or ZERO) if manager_id else ZERO,
            manager_net_revenue=((gross.get(manager_id) or ZERO) - (spent.get(manager_id) or ZERO))
            if manager_id
            else ZERO,
            last_activity=max((p.updated_at for p in mine), default=None),
        )
        for p in mine:
            a = activity.get(p.id)
            if a is None:
                continue
            row.tasks_created += a.created
            row.tasks_completed += a.completed
            row.tasks_open += a.open
            row.tasks_overdue += a.overdue
            if a.last_activity and (row.last_activity is None or a.last_activity > row.last_activity):
                row.last_activity = a.last_activity
        row.stale = bool(mine) and (
            row.last_activity is None or (today - row.last_activity.date()).days >= HIRE_STALE_DAYS
        )
        rows.append(row)
    rows.sort(key=lambda r: (r.hire_name.lower(), (r.manager_name or "").lower()))

    if format != "json":
        return export_response(
            format,
            f"hired-managers_{date_from}_{date_to}",
            [
                "hire",
                "project manager",
                "projects",
                "tasks created",
                "tasks completed",
                "tasks open",
                "tasks overdue",
                "last activity",
                "paid",
                "manager gross revenue",
                "manager net revenue",
            ],
            (
                [
                    r.hire_name,
                    r.manager_name or "",
                    r.projects,
                    r.tasks_created,
                    r.tasks_completed,
                    r.tasks_open,
                    r.tasks_overdue,
                    r.last_activity.date() if r.last_activity else "",
                    r.paid,
                    r.manager_gross_revenue,
                    r.manager_net_revenue,
                ]
                for r in rows
            ),
            title=f"Hired managers, {date_from} to {date_to}",
        )
    return HiredManagersOut(
        date_from=date_from,
        date_to=date_to,
        base_currency=(await settings.base_currency(session)).code,
        stale_after_days=HIRE_STALE_DAYS,
        rows=rows,
    )


# ---- monthly summary (salary periods) --------------------------------------------------------------


class HirePay(BaseModel):
    hire_id: uuid.UUID
    hire_name: str
    amount: Decimal


class MonthRow(BaseModel):
    period_id: uuid.UUID | None
    label: str
    start_date: date
    end_date: date
    status: str
    income: Decimal
    expenses: Decimal
    salary_paid: Decimal
    profit: Decimal
    salary_calculated: Decimal
    margin_pct: Decimal | None = None  # profit / income
    fees: Decimal = ZERO  # payment fees the company paid (included in expenses)
    shared_expenses: Decimal = ZERO  # one employee: their share of split expenses (included in expenses)
    hired_manager_pay: Decimal = ZERO  # selected employees: what their hires were paid (included in expenses)
    hire_payments: list[HirePay] = []  # the same, per hire
    fx_gain_loss: Decimal = ZERO  # realized (included in income); negative = loss
    cash_in: Decimal = ZERO
    cash_out: Decimal = ZERO
    closing_cash: Decimal = ZERO  # money accounts as recorded, at the period end
    in_progress: bool = False


class MonthlySummaryOut(BaseModel):
    base_currency: str
    rows: list[MonthRow]
    totals: MonthRow | None
    # A selection (see _selection_months); none of these set = the whole company.
    employee_ids: list[uuid.UUID] = []
    employee_names: list[str] = []
    unassigned: bool = False


async def _check_salary_visible(session: AsyncSession, user: CurrentUser, employee_ids: list[uuid.UUID]) -> None:
    """Same rule as the salary reports: everyone, or only yourself and your projects' teams."""
    scope = user.scope_for("salary.read")
    if scope is None:
        raise Forbidden("You cannot see employee salary figures")
    if scope != Scope.ALL:
        own = await employees.for_user(session, user.id)
        visible = {own.id} if own else set()
        if scope == Scope.PROJECT:
            visible |= await projects.team_ids(session, await projects.visible_project_ids(session, user))
        if set(employee_ids) - visible:
            raise NotFound("Employee not found")
    for employee_id in employee_ids:
        await employees.get(session, employee_id)


def _parse_ids(raw: str | None) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for part in (raw or "").split(","):
        if not part.strip():
            continue
        try:
            value = uuid.UUID(part.strip())
        except ValueError:
            raise ValidationFailed(
                "Invalid employee id", errors=[field_error("employee_ids", f"Not an id: {part.strip()}")]
            ) from None
        if value not in ids:
            ids.append(value)
    return ids


async def _selection_months(
    session: AsyncSession, cols: list[PeriodCol], today: date, employee_ids: list[uuid.UUID], unassigned: bool
) -> list[MonthRow]:
    """Employees and/or the unassigned part of the company, summed per month.

    An employee carries the revenue credited to them, the expenses tagged to them plus their share of split
    expenses, and the salary they earned. Unassigned is what nobody carries: company income and expenses less
    every employee's, with no salary (fees, overhead, unsplit receipts). Employees plus unassigned add up to the
    company, except that salary counts as earned here and as paid in the company view. Cash stays zero."""
    bal = await salary.balances(session, None if unassigned else employee_ids, until=today)
    company = {r.period_id: r for r in await _company_months(session, cols, today)} if unassigned else {}
    chosen = set(employee_ids)
    hires_by_party = {h.party_id: h for h in await employees.all_hires(session)} if chosen else {}
    rows = []
    for p in cols:
        lines = [line for b in bal.values() for line in b.lines if line.period.id == p.id]
        mine = [line for line in lines if line.employee_id in chosen]
        everyone_shared = await attribution.expense_totals(session, date_from=p.start_date, date_to=p.end_date)
        shared = sum((v for e, v in everyone_shared.items() if e in chosen), ZERO)
        income = sum((line.gross_revenue for line in mine), ZERO)
        expenses = sum((line.expenses for line in mine), ZERO) + shared
        earned = sum((line.calculated for line in mine), ZERO)
        paid = sum((line.paid for line in mine), ZERO)  # paid toward this month, whenever it was paid
        fees = fx = ZERO
        if unassigned:
            c = company[p.id]
            income += c.income - sum((line.gross_revenue for line in lines), ZERO)
            expenses += c.expenses - sum((line.expenses for line in lines), ZERO) - sum(everyone_shared.values(), ZERO)
            fees, fx = c.fees, c.fx_gain_loss
        profit = income - expenses - earned
        hire_pay: dict[uuid.UUID, Decimal] = {}
        for (party, employee), amount in (
            await payments.hire_paid_totals(
                session, party_ids=list(hires_by_party), date_from=p.start_date, date_to=p.end_date
            )
        ).items():
            if employee in chosen:
                hire = hires_by_party[party]
                hire_pay[hire.id] = hire_pay.get(hire.id, ZERO) + amount
        names = {h.id: h.full_name for h in hires_by_party.values()}
        rows.append(
            MonthRow(
                period_id=p.id,
                label=p.label,
                start_date=p.start_date,
                end_date=p.end_date,
                status=p.status,
                income=income,
                expenses=expenses,
                salary_paid=paid,
                profit=profit,
                salary_calculated=earned,
                margin_pct=pct(profit, income) if income > 0 else None,
                fees=fees,
                fx_gain_loss=fx,
                shared_expenses=shared,
                hired_manager_pay=sum(hire_pay.values(), ZERO),
                hire_payments=sorted(
                    (HirePay(hire_id=h, hire_name=names[h], amount=a) for h, a in hire_pay.items()),
                    key=lambda x: x.hire_name.lower(),
                ),
                in_progress=p.in_progress,
            )
        )
    return rows


async def _company_months(session: AsyncSession, cols: list[PeriodCol], today: date) -> list[MonthRow]:
    at = bucketer(cols)
    n = len(cols)
    first, last = cols[0].start_date, cols[-1].end_date
    bal = await salary.balances(session, None, until=today)
    calculated: dict[uuid.UUID, Decimal] = {}
    for b in bal.values():
        for line in b.lines:
            calculated[line.period.id] = calculated.get(line.period.id, ZERO) + line.calculated
    sums = [{"income": ZERO, "expenses": ZERO, "salary": ZERO, "fees": ZERO, "fx": ZERO} for _ in cols]
    for pl in await accounting.pl_by_day(session, first, last):
        i = at(pl.day)
        if i is None:
            continue
        acc = sums[i]
        if pl.root_type == "income":
            acc["income"] += pl.amount
            if pl.system_key == "fx_gain_loss":
                acc["fx"] += pl.amount
        elif pl.system_key == "salary_expense":
            acc["salary"] += pl.amount
        else:
            acc["expenses"] += pl.amount
            if pl.system_key == "bank_fees":
                acc["fees"] += pl.amount
    cash_in, cash_out = [ZERO] * n, [ZERO] * n
    # Totals per kind (income, expense, salary, equity, other) first, so a payment and its cancellation
    # cancel out instead of counting once as money in and once as money out.
    kinds: list[dict[str, Decimal]] = [{} for _ in cols]
    for day, parts in await accounting.cash_flows(session, first, last):
        i = at(day)
        if i is not None:
            for k, v in parts.items():
                kinds[i][k] = kinds[i].get(k, ZERO) + v
    for i, totals in enumerate(kinds):
        cash_in[i] = sum((v for v in totals.values() if v > 0), ZERO)
        cash_out[i] = -sum((v for v in totals.values() if v < 0), ZERO)
    cash = await accounting.cash_balance(session, first - timedelta(days=1))
    rows = []
    for i, p in enumerate(cols):
        acc = sums[i]
        profit = acc["income"] - acc["expenses"] - acc["salary"]
        cash += cash_in[i] - cash_out[i]
        rows.append(
            MonthRow(
                period_id=p.id,
                label=p.label,
                start_date=p.start_date,
                end_date=p.end_date,
                status=p.status,
                income=acc["income"],
                expenses=acc["expenses"],
                salary_paid=acc["salary"],
                profit=profit,
                salary_calculated=calculated.get(p.id, ZERO),
                margin_pct=pct(profit, acc["income"]) if acc["income"] > 0 else None,
                fees=acc["fees"],
                fx_gain_loss=acc["fx"],
                cash_in=cash_in[i],
                cash_out=cash_out[i],
                closing_cash=cash,
                in_progress=p.in_progress,
            )
        )
    return rows


@router.get("/reports/monthly-summary", response_model=MonthlySummaryOut)
async def monthly_summary(
    periods: Annotated[int, Query(ge=0, le=36, description="0 = all time")] = 12,
    employee_ids: Annotated[str | None, Query(description="Comma-separated employee ids")] = None,
    unassigned: bool = False,
    format: Format = "json",
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Income, expenses, salary and profit per month, where a month is a salary period (Settings > Salary Cycle).
    With `employee_ids` and/or `unassigned`: the same months for that selection (see _selection_months)."""
    ids = _parse_ids(employee_ids)
    # The company and its unassigned part need reports.financial; employees' own months need salary.read
    # (an employee sees themselves, a project scope their teams).
    if not user.can("reports.financial") and (not ids or unassigned):
        raise Forbidden("Only your own months (or your teams') are available to you")
    cols, today = await recent_periods(session, periods or None)
    names: list[str] = []
    if ids or unassigned:
        if ids:
            await _check_salary_visible(session, user, ids)
            found = await employees.names(session, ids)
            names = [found.get(i, "?") for i in ids]
        rows = await _selection_months(session, cols, today, ids, unassigned)
    else:
        rows = await _company_months(session, cols, today)
    await session.commit()
    totals = None
    if rows:
        totals = MonthRow(
            period_id=None,
            label="Total",
            start_date=rows[0].start_date,
            end_date=rows[-1].end_date,
            status="",
            income=sum((r.income for r in rows), ZERO),
            expenses=sum((r.expenses for r in rows), ZERO),
            salary_paid=sum((r.salary_paid for r in rows), ZERO),
            profit=sum((r.profit for r in rows), ZERO),
            salary_calculated=sum((r.salary_calculated for r in rows), ZERO),
            fees=sum((r.fees for r in rows), ZERO),
            shared_expenses=sum((r.shared_expenses for r in rows), ZERO),
            hired_manager_pay=sum((r.hired_manager_pay for r in rows), ZERO),
            fx_gain_loss=sum((r.fx_gain_loss for r in rows), ZERO),
            cash_in=sum((r.cash_in for r in rows), ZERO),
            cash_out=sum((r.cash_out for r in rows), ZERO),
            closing_cash=rows[-1].closing_cash,
        )
        totals.margin_pct = pct(totals.profit, totals.income) if totals.income > 0 else None
    if format != "json":
        picked = [*names, *(["Not assigned"] if unassigned else [])]
        who = f" - {', '.join(picked)}" if picked else ""
        return export_response(
            format,
            "monthly-summary-selection" if picked else "monthly-summary",
            [
                "month",
                "from",
                "to",
                "income",
                "expenses",
                "salary paid",
                "profit",
                "margin %",
                "salary calculated",
                "fees",
                "hired manager pay",
                "cash in",
                "cash out",
                "closing cash",
            ],
            [
                [
                    r.label,
                    r.start_date,
                    r.end_date,
                    r.income,
                    r.expenses,
                    r.salary_paid,
                    r.profit,
                    r.margin_pct,
                    r.salary_calculated,
                    r.fees,
                    r.hired_manager_pay,
                    r.cash_in,
                    r.cash_out,
                    r.closing_cash,
                ]
                for r in [*rows, *([totals] if totals else [])]
            ],
            title=f"Monthly summary (salary periods){who}",
        )
    return MonthlySummaryOut(
        base_currency=(await settings.base_currency(session)).code,
        rows=rows,
        totals=totals,
        employee_ids=ids,
        employee_names=names,
        unassigned=unassigned,
    )


# ---- company dashboard -----------------------------------------------------------------------------


class AtRisk(BaseModel):
    project_id: uuid.UUID
    number: str
    name: str
    reasons: list[str]


class Upcoming(BaseModel):
    kind: str  # milestone | deadline
    title: str
    date: date
    project_id: uuid.UUID
    link: str


class DashboardOut(BaseModel):
    base_currency: str
    period_label: str
    period_start: date
    period_end: date
    cash_book: Decimal
    cash_market: Decimal
    income: Decimal
    expenses: Decimal
    salary_paid: Decimal
    profit: Decimal
    salary_owed: Decimal  # earned by employees, not yet paid (all periods)
    salary_projected: Decimal  # this period's calculated salary so far
    tasks_open: int
    tasks_overdue: int
    tasks_due_soon: int
    projects_active: int
    at_risk: list[AtRisk]
    upcoming: list[Upcoming]


def _risk_reasons(p: Any, f: ProjectFinancialsOut, today: date) -> list[str]:
    reasons = []
    if p.deadline and p.deadline < today:
        reasons.append(f"past its deadline ({p.deadline.isoformat()})")
    if f.budget_remaining is not None and f.budget_remaining < 0:
        reasons.append("over budget")
    if f.tasks_overdue:
        reasons.append(f"{f.tasks_overdue} overdue task{'s' if f.tasks_overdue > 1 else ''}")
    if f.profit_incl_owed < 0:
        reasons.append("losing money")
    return reasons


@router.get("/dashboard/company", response_model=DashboardOut)
async def company_dashboard(_: CurrentUser = Report, session: AsyncSession = Depends(get_session)) -> DashboardOut:
    """Company at a glance. "This month" is the current salary period."""
    today = await settings.today(session)
    period = await salary.period_for(session, today)
    t = await accounting.period_totals(session, period.start_date, period.end_date)
    h = await accounting.holdings(session, today)
    book = sum((x.book_value for x in h), ZERO)
    market = sum((x.market_value if x.market_value is not None else x.book_value for x in h), ZERO)
    bal = await salary.balances(session, None, until=today)
    owed = sum((max(b.balance, ZERO) for b in bal.values()), ZERO)
    projected = sum((line.calculated for b in bal.values() for line in b.lines if line.period.id == period.id), ZERO)
    counts = await tasks.counts(session, today=today)
    stmt = projects.list_stmt(q=None, status="active", customer_party_id=None, only_ids=None)
    active = list((await session.execute(stmt)).scalars())
    fin = {f.project_id: f for f in await _financials(session, active, None, None)}
    risks = []
    for p in active:
        reasons = _risk_reasons(p, fin[p.id], today)
        if reasons:
            risks.append(AtRisk(project_id=p.id, number=p.number, name=p.name, reasons=reasons))
    soon = date.fromordinal(today.toordinal() + 14)
    upcoming = [
        Upcoming(
            kind="milestone",
            title=m.name,
            date=m.due_date,
            project_id=m.project_id,
            link=f"/projects/{m.project_id}?tab=timeline",
        )
        for m in await projects.milestones_between(session, None, today, soon)
        if m.status not in ("done", "cancelled") and m.due_date
    ] + [
        Upcoming(kind="deadline", title=p.name, date=p.deadline, project_id=p.id, link=f"/projects/{p.id}")
        for p in await projects.deadlines_between(session, None, today, soon)
        if p.deadline
    ]
    upcoming.sort(key=lambda u: u.date)
    await session.commit()
    return DashboardOut(
        base_currency=(await settings.base_currency(session)).code,
        period_label=period.label,
        period_start=period.start_date,
        period_end=period.end_date,
        cash_book=book,
        cash_market=market,
        income=t.income,
        expenses=t.expenses,
        salary_paid=t.salary,
        profit=t.profit,
        salary_owed=owed,
        salary_projected=projected,
        tasks_open=counts["open"],
        tasks_overdue=counts["overdue"],
        tasks_due_soon=counts["due_soon"],
        projects_active=len(active),
        at_risk=risks,
        upcoming=upcoming[:12],
    )
