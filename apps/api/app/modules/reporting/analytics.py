"""Trend and analysis reports: cash flow and runway, customers, expense trends, project trends.

Columns are salary periods (the company's "month"). Everything reads other modules' facades only."""

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
from app.core.money import quantize
from app.modules.accounting import api as accounting
from app.modules.auth.api import CurrentUser, require
from app.modules.categories import api as categories
from app.modules.payments import api as payments
from app.modules.projects import api as projects
from app.modules.rbac.api import Scope
from app.modules.reporting.periods import ZERO, PeriodCol, bucketer, completed, pct, recent_periods
from app.modules.settings import api as settings

router = APIRouter(tags=["reports"])

Report = Depends(require("reports.financial"))
Financials = Depends(require("projects.read_financials", Scope.PROJECT))
Periods = Annotated[int, Query(ge=2, le=36)]

LAPSING_DAYS = 60
LAPSED_DAYS = 90


def _avg(values: list[Decimal]) -> Decimal:
    return sum(values, ZERO) / len(values) if values else ZERO


# ---- cash flow & runway ----------------------------------------------------------------------------


class CashRow(BaseModel):
    """Where money came from and went, by what was on the other side of each payment. Transfers between our
    own accounts cancel out; their fees count as expenses and exchange differences as income."""

    income: Decimal  # received for income (customer payments, other income)
    expenses: Decimal  # paid for expenses other than salary (positive)
    salary: Decimal  # salary paid (positive)
    owner_in: Decimal  # capital the owners put in
    owner_out: Decimal  # drawings taken out (positive)
    other: Decimal  # loans, other assets and liabilities; signed (in = positive)
    net: Decimal  # change in money accounts
    closing_book: Decimal  # as recorded
    closing_market: Decimal  # at the saved rate on the period's last day (today for the current period)
    fees: Decimal  # payment fees the company paid
    fx_gain_loss: Decimal  # realized; negative = loss


class CurrencyRow(BaseModel):
    currency: str
    units: list[Decimal]  # held at each period end
    values: list[Decimal]  # in the base currency at the saved rate
    share_pct: Decimal | None  # of today's total


class FeeRow(BaseModel):
    account_name: str
    currency: str
    paid_by: str  # company | client
    payments: int
    amount: Decimal  # base currency


class Runway(BaseModel):
    cash_now: Decimal  # money accounts at today's saved rates
    avg_in: Decimal  # income received per completed period, over the last three
    avg_out: Decimal  # expenses + salary paid
    net_burn: Decimal  # avg_out - avg_in (negative = cash is growing)
    months_net: Decimal | None  # cash_now / net_burn; None when cash is growing
    months_if_no_income: Decimal | None  # cash_now / avg_out
    basis_periods: int


class CashFlowOut(BaseModel):
    base_currency: str
    periods: list[PeriodCol]
    rows: list[CashRow]
    currencies: list[CurrencyRow]
    fees_by_account: list[FeeRow]
    runway: Runway


@router.get("/reports/cash-flow", response_model=CashFlowOut)
async def cash_flow(
    periods: Periods = 12,
    format: Format = "json",
    _user: CurrentUser = Report,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Money in and out per period by source (income, expenses, salary, owner), cash held at each period end
    (in total and per currency), fees, and runway."""
    cols, today = await recent_periods(session, periods)
    first, last = cols[0].start_date, cols[-1].end_date
    at = bucketer(cols)
    n = len(cols)
    flow = {k: [ZERO] * n for k in ("income", "expense", "salary", "owner_in", "owner_out", "other")}
    for day, parts in await accounting.cash_flows(session, first, last):
        i = at(day)
        if i is None:
            continue
        flow["income"][i] += parts["income"]
        flow["expense"][i] -= parts["expense"]
        flow["salary"][i] -= parts["salary"]
        flow["owner_in" if parts["equity"] > 0 else "owner_out"][i] += abs(parts["equity"])
        flow["other"][i] += parts["other"]
    fees, fx = [ZERO] * n, [ZERO] * n
    for line in await accounting.pl_by_day(session, first, last):
        i = at(line.day)
        if i is None:
            continue
        if line.system_key == "bank_fees":
            fees[i] += line.amount
        elif line.system_key == "fx_gain_loss":
            fx[i] += line.amount

    opening = await accounting.cash_balance(session, first - timedelta(days=1))
    rows: list[CashRow] = []
    by_currency: dict[str, tuple[list[Decimal], list[Decimal]]] = {}
    book = opening
    for i, p in enumerate(cols):
        net = (
            flow["income"][i]
            - flow["expense"][i]
            - flow["salary"][i]
            + flow["owner_in"][i]
            - flow["owner_out"][i]
            + flow["other"][i]
        )
        book += net
        held = await accounting.holdings(session, min(p.end_date, today))
        market = ZERO
        for h in held:
            value = h.market_value if h.market_value is not None else h.book_value
            market += value
            units, values = by_currency.setdefault(h.currency, ([ZERO] * n, [ZERO] * n))
            units[i] += h.units
            values[i] += value
        rows.append(
            CashRow(
                income=flow["income"][i],
                expenses=flow["expense"][i],
                salary=flow["salary"][i],
                owner_in=flow["owner_in"][i],
                owner_out=flow["owner_out"][i],
                other=flow["other"][i],
                net=net,
                closing_book=book,
                closing_market=market,
                fees=fees[i],
                fx_gain_loss=fx[i],
            )
        )

    cash_now = rows[-1].closing_market if rows else ZERO
    currencies = sorted(
        (
            CurrencyRow(currency=c, units=u, values=v, share_pct=pct(v[-1], cash_now) if v else None)
            for c, (u, v) in by_currency.items()
            if any(u)
        ),
        key=lambda r: -r.values[-1],
    )
    base = await settings.base_currency(session)
    basis = completed(cols)[-3:]
    # Runway runs on the business alone: income against expenses and salary. Owner money is not income.
    avg_in = quantize(_avg([flow["income"][i] for i in basis]), base.precision)
    avg_out = quantize(_avg([flow["expense"][i] + flow["salary"][i] for i in basis]), base.precision)
    burn = avg_out - avg_in
    # Runway only means something with cash in hand (no opening balances yet = negative cash).
    has_cash = cash_now > 0
    runway = Runway(
        cash_now=cash_now,
        avg_in=avg_in,
        avg_out=avg_out,
        net_burn=burn,
        months_net=(cash_now / burn).quantize(Decimal("0.1")) if has_cash and burn > 0 else None,
        months_if_no_income=(cash_now / avg_out).quantize(Decimal("0.1")) if has_cash and avg_out > 0 else None,
        basis_periods=len(basis),
    )
    fee_rows = sorted(
        (
            FeeRow(account_name=name, currency=cur, paid_by=by, payments=k, amount=quantize(amount, base.precision))
            for name, cur, by, k, amount in await payments.fee_totals(session, date_from=first, date_to=last)
        ),
        key=lambda r: -r.amount,
    )
    await session.commit()
    if format != "json":
        return export_response(
            format,
            "cash-flow",
            [
                "month",
                "from",
                "to",
                "income",
                "expenses",
                "salary",
                "owner in",
                "owner drawings",
                "other",
                "net change",
                "closing (recorded)",
                "closing (today's rates)",
            ],
            [
                [
                    p.label,
                    p.start_date,
                    p.end_date,
                    r.income,
                    r.expenses,
                    r.salary,
                    r.owner_in,
                    r.owner_out,
                    r.other,
                    r.net,
                    r.closing_book,
                    r.closing_market,
                ]
                for p, r in zip(cols, rows, strict=True)
            ],
            title="Cash flow (salary periods)",
        )
    return CashFlowOut(
        base_currency=base.code,
        periods=cols,
        rows=rows,
        currencies=currencies,
        fees_by_account=fee_rows,
        runway=runway,
    )


# ---- customers -------------------------------------------------------------------------------------


class CustomerRow(BaseModel):
    party_id: uuid.UUID
    party_name: str
    by_period: list[Decimal]
    total: Decimal
    payments: int
    share_pct: Decimal | None
    first_payment: date | None
    last_payment: date | None
    days_since_last: int | None
    status: str  # new | active | lapsing | lapsed


class CustomerPeriod(BaseModel):
    revenue: Decimal
    paying_customers: int
    new_customers: int


class Concentration(BaseModel):
    top1_pct: Decimal | None
    top3_pct: Decimal | None
    top5_pct: Decimal | None


class CustomersOut(BaseModel):
    base_currency: str
    periods: list[PeriodCol]
    by_period: list[CustomerPeriod]
    rows: list[CustomerRow]
    total: Decimal
    concentration: Concentration
    lapsing_days: int
    lapsed_days: int


def _customer_status(first: date | None, last: date | None, today: date, current: PeriodCol) -> str:
    if first and first >= current.start_date:
        return "new"
    if last is None:
        return "lapsed"
    days = (today - last).days
    return "active" if days <= LAPSING_DAYS else "lapsing" if days <= LAPSED_DAYS else "lapsed"


@router.get("/reports/customers", response_model=CustomersOut)
async def customer_analysis(
    periods: Periods = 12,
    format: Format = "json",
    _user: CurrentUser = Report,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Received payments per customer per period, concentration, new and lapsing customers."""
    cols, today = await recent_periods(session, periods)
    at = bucketer(cols)
    n = len(cols)
    first, last = cols[0].start_date, cols[-1].end_date
    amounts: dict[uuid.UUID, list[Decimal]] = {}
    counts: dict[uuid.UUID, int] = {}
    revenue = [ZERO] * n
    paying: list[set[uuid.UUID]] = [set() for _ in cols]
    for party, day, k, total in await payments.party_daily_totals(
        session, direction="receive", date_from=first, date_to=last
    ):
        i = at(day)
        if i is None:
            continue
        revenue[i] += total
        if party is None:
            continue
        amounts.setdefault(party, [ZERO] * n)[i] += total
        counts[party] = counts.get(party, 0) + k
        paying[i].add(party)
    first_last = await payments.party_first_last(session, direction="receive")
    # Customers who paid before this window but not in it are the ones going quiet: keep them in view.
    for party, (_, last_day) in first_last.items():
        if party not in amounts and (today - last_day).days <= 365:
            amounts[party] = [ZERO] * n
    names = await lookup.resolve(session, "party", list(amounts))
    grand = sum((sum(v, ZERO) for v in amounts.values()), ZERO)
    rows = []
    for party, values in amounts.items():
        fl = first_last.get(party)
        total = sum(values, ZERO)
        rows.append(
            CustomerRow(
                party_id=party,
                party_name=names.get(party, "?"),
                by_period=values,
                total=total,
                payments=counts.get(party, 0),
                share_pct=pct(total, grand),
                first_payment=fl[0] if fl else None,
                last_payment=fl[1] if fl else None,
                days_since_last=(today - fl[1]).days if fl else None,
                status=_customer_status(fl[0] if fl else None, fl[1] if fl else None, today, cols[-1]),
            )
        )
    rows.sort(key=lambda r: (-r.total, r.party_name.lower()))
    tops = [r.total for r in rows]
    new_counts = [0] * n
    for first_day, _last_day in first_last.values():
        i = at(first_day)
        if i is not None:
            new_counts[i] += 1
    await session.commit()
    if format != "json":
        return export_response(
            format,
            "customers",
            ["customer", *(p.label for p in cols), "total", "share %", "last payment", "days since", "status"],
            [
                [r.party_name, *r.by_period, r.total, r.share_pct, r.last_payment, r.days_since_last, r.status]
                for r in rows
            ],
            title="Customer revenue by month",
        )
    return CustomersOut(
        base_currency=(await settings.base_currency(session)).code,
        periods=cols,
        by_period=[
            CustomerPeriod(revenue=revenue[i], paying_customers=len(paying[i]), new_customers=new_counts[i])
            for i in range(n)
        ],
        rows=rows,
        total=grand,
        concentration=Concentration(
            top1_pct=pct(sum(tops[:1], ZERO), grand),
            top3_pct=pct(sum(tops[:3], ZERO), grand),
            top5_pct=pct(sum(tops[:5], ZERO), grand),
        ),
        lapsing_days=LAPSING_DAYS,
        lapsed_days=LAPSED_DAYS,
    )


# ---- income / expense trends -----------------------------------------------------------------------


class TrendRow(BaseModel):
    key: str
    account_id: uuid.UUID | None = None
    account_code: str | None = None
    account_name: str | None = None
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    party_id: uuid.UUID | None = None
    party_name: str | None = None
    by_period: list[Decimal]
    total: Decimal
    change: Decimal | None  # last completed period vs the one before
    change_pct: Decimal | None


class TrendsOut(BaseModel):
    kind: str
    base_currency: str
    periods: list[PeriodCol]
    compare: list[int]  # indexes of the two periods `change` compares (older, newer); empty if fewer
    categories: list[TrendRow]
    parties: list[TrendRow]  # suppliers (expense) or customers (income)
    totals: list[Decimal]


def _change(values: list[Decimal], compare: list[int]) -> tuple[Decimal | None, Decimal | None]:
    if len(compare) < 2:
        return None, None
    old, new = values[compare[0]], values[compare[1]]
    return new - old, pct(new - old, old) if old else None


@router.get("/reports/trends", response_model=TrendsOut)
async def trends(
    kind: Literal["income", "expense"] = "expense",
    periods: Periods = 6,
    format: Format = "json",
    _user: CurrentUser = Report,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Income or expenses per account / category and per party, per period, with the latest change."""
    cols, _today = await recent_periods(session, periods)
    at = bucketer(cols)
    n = len(cols)
    first, last = cols[0].start_date, cols[-1].end_date
    done = completed(cols)
    compare = done[-2:] if len(done) >= 2 else []

    by_cat: dict[tuple[uuid.UUID, uuid.UUID | None], TrendRow] = {}
    for line in await accounting.pl_by_day(session, first, last):
        i = at(line.day)
        if i is None or line.root_type != kind:
            continue
        row = by_cat.get((line.account_id, line.category_id))
        if row is None:
            row = by_cat[(line.account_id, line.category_id)] = TrendRow(
                key=f"{line.account_id}:{line.category_id or ''}",
                account_id=line.account_id,
                account_code=line.code,
                account_name=line.name,
                category_id=line.category_id,
                by_period=[ZERO] * n,
                total=ZERO,
                change=None,
                change_pct=None,
            )
        row.by_period[i] += line.amount
    cat_names = {}
    for cid in {k[1] for k in by_cat if k[1]}:
        cat_names[cid] = (await categories.get(session, cid)).name

    by_party: dict[uuid.UUID | None, list[Decimal]] = {}
    direction = "pay" if kind == "expense" else "receive"
    for party, day, _k, total in await payments.party_daily_totals(
        session, direction=direction, date_from=first, date_to=last
    ):
        i = at(day)
        if i is not None:
            by_party.setdefault(party, [ZERO] * n)[i] += total
    party_names = await lookup.resolve(session, "party", [p for p in by_party if p])

    cat_rows = list(by_cat.values())
    for r in cat_rows:
        r.category_name = cat_names.get(r.category_id) if r.category_id else None
        r.total = sum(r.by_period, ZERO)
        r.change, r.change_pct = _change(r.by_period, compare)
    party_rows = []
    for p, values in by_party.items():
        change, change_pct = _change(values, compare)
        party_rows.append(
            TrendRow(
                key=str(p or "none"),
                party_id=p,
                party_name=party_names.get(p, "?") if p else "No party",
                by_period=values,
                total=sum(values, ZERO),
                change=change,
                change_pct=change_pct,
            )
        )
    cat_rows.sort(key=lambda r: -r.total)
    party_rows.sort(key=lambda r: -r.total)
    totals = [sum((r.by_period[i] for r in cat_rows), ZERO) for i in range(n)]
    await session.commit()
    if format != "json":
        return export_response(
            format,
            f"{kind}-trends",
            ["account", "category", *(p.label for p in cols), "total", "change"],
            [
                [f"{r.account_code} {r.account_name}", r.category_name or "-", *r.by_period, r.total, r.change]
                for r in cat_rows
            ],
            title=("Income" if kind == "income" else "Expense") + " trends",
        )
    return TrendsOut(
        kind=kind,
        base_currency=(await settings.base_currency(session)).code,
        periods=cols,
        compare=compare,
        categories=cat_rows,
        parties=party_rows,
        totals=totals,
    )


# ---- one project over time -------------------------------------------------------------------------


class ProjectTrendRow(BaseModel):
    revenue: Decimal
    costs: Decimal  # direct expenses + salary
    profit: Decimal
    cumulative_revenue: Decimal
    cumulative_costs: Decimal


class ProjectTrendOut(BaseModel):
    base_currency: str
    budget: Decimal | None
    contract_value: Decimal | None
    periods: list[PeriodCol]
    rows: list[ProjectTrendRow]
    before: ProjectTrendRow  # everything posted before the first period


@router.get("/projects/{project_id}/financials/trend", response_model=ProjectTrendOut)
async def project_trend(
    project_id: uuid.UUID,
    periods: Periods = 12,
    user: CurrentUser = Financials,
    session: AsyncSession = Depends(get_session),
) -> ProjectTrendOut:
    """Revenue, costs and profit per period for one project, with running totals against budget and contract."""
    project = await projects.get(session, project_id)
    await projects.ensure_visible(session, user, "projects.read_financials", project)
    cols, _today = await recent_periods(session, periods)
    at = bucketer(cols)
    n = len(cols)
    revenue, costs = [ZERO] * n, [ZERO] * n
    for line in await accounting.pl_by_day(session, cols[0].start_date, cols[-1].end_date, project_ids=[project_id]):
        i = at(line.day)
        if i is None:
            continue
        if line.root_type == "income":
            revenue[i] += line.amount
        else:
            costs[i] += line.amount
    prior = (await accounting.project_ledger(session, [project_id], date_to=cols[0].start_date - timedelta(days=1)))[
        project_id
    ]
    cum_rev, cum_cost = prior.income, prior.expenses + prior.salary
    rows = []
    for i in range(n):
        cum_rev += revenue[i]
        cum_cost += costs[i]
        rows.append(
            ProjectTrendRow(
                revenue=revenue[i],
                costs=costs[i],
                profit=revenue[i] - costs[i],
                cumulative_revenue=cum_rev,
                cumulative_costs=cum_cost,
            )
        )
    await session.commit()
    before_costs = prior.expenses + prior.salary
    return ProjectTrendOut(
        base_currency=(await settings.base_currency(session)).code,
        budget=project.budget,
        contract_value=project.contract_value,
        periods=cols,
        rows=rows,
        before=ProjectTrendRow(
            revenue=prior.income,
            costs=before_costs,
            profit=prior.income - before_costs,
            cumulative_revenue=prior.income,
            cumulative_costs=before_costs,
        ),
    )
