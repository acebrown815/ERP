"""Cross-module reports. Reads other modules' facades only; owns no tables."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.core.db import get_session
from app.core.exports import Format, export_response
from app.modules.accounting import api as accounting
from app.modules.attribution import api as attribution
from app.modules.auth.api import CurrentUser, require
from app.modules.categories import api as categories
from app.modules.payments import api as payments
from app.modules.projects import api as projects
from app.modules.rbac.api import Scope
from app.modules.reporting.periods import bucketer, pct, recent_periods
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
    """Every visible project's financials, most profitable first."""
    only = None
    if user.scope_for("projects.read_financials") != Scope.ALL:
        only = await projects.visible_project_ids(session, user)
    stmt = projects.list_stmt(q=None, status=status, customer_party_id=None, only_ids=only)
    rows = list((await session.execute(stmt.limit(500))).scalars())
    out = sorted(await _financials(session, rows, date_from, date_to), key=lambda r: -r.profit_cash)
    await session.commit()
    if format != "json":
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
            "revenue_per_hour",
        ]
        return export_response(format, "project-profitability", fields, ([getattr(r, f) for f in fields] for r in out))
    return out


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


# ---- monthly summary (salary periods) --------------------------------------------------------------


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
    fx_gain_loss: Decimal = ZERO  # realized (included in income); negative = loss
    cash_in: Decimal = ZERO
    cash_out: Decimal = ZERO
    closing_cash: Decimal = ZERO  # money accounts as recorded, at the period end
    in_progress: bool = False


class MonthlySummaryOut(BaseModel):
    base_currency: str
    rows: list[MonthRow]
    totals: MonthRow | None


@router.get("/reports/monthly-summary", response_model=MonthlySummaryOut)
async def monthly_summary(
    periods: Annotated[int, Query(ge=1, le=36)] = 12,
    format: Format = "json",
    _: CurrentUser = Report,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Income, expenses, salary and profit per month, where a month is a salary period (Settings > Salary Cycle)."""
    cols, today = await recent_periods(session, periods)
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
            fx_gain_loss=sum((r.fx_gain_loss for r in rows), ZERO),
            cash_in=sum((r.cash_in for r in rows), ZERO),
            cash_out=sum((r.cash_out for r in rows), ZERO),
            closing_cash=rows[-1].closing_cash,
        )
        totals.margin_pct = pct(totals.profit, totals.income) if totals.income > 0 else None
    if format != "json":
        return export_response(
            format,
            "monthly-summary",
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
                    r.cash_in,
                    r.cash_out,
                    r.closing_cash,
                ]
                for r in [*rows, *([totals] if totals else [])]
            ],
            title="Monthly summary (salary periods)",
        )
    return MonthlySummaryOut(base_currency=(await settings.base_currency(session)).code, rows=rows, totals=totals)


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
