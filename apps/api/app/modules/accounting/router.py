import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.core.csv_export import csv_response
from app.core.db import get_session
from app.core.errors import Conflict, NotFound, ValidationFailed, field_error
from app.core.idempotency import run_idempotent
from app.core.money import quantize
from app.core.pagination import Page, PageParams, page_params, paginate
from app.modules.accounting import reports, service
from app.modules.accounting.models import ACCOUNT_TYPES, Account, JournalEntry, JournalLine
from app.modules.auth.api import CurrentUser, require, require_any
from app.modules.settings import api as settings

router = APIRouter(tags=["accounting"])

Money = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=4)]


# ---- schemas ---------------------------------------------------------------------------------------


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    parent_id: uuid.UUID | None
    root_type: str
    account_type: str
    is_group: bool
    currency: str
    description: str | None
    is_active: bool
    system_key: str | None
    version: int
    depth: int = 0
    balance: Decimal = Decimal(0)  # base currency, as recorded
    has_postings: bool = False
    # Accounts in another currency (USDT wallet, EUR bank...): balance in that currency and its value at
    # the saved rate on the date. Groups get the rolled-up value at today's rates. Display only.
    balance_in_currency: Decimal | None = None
    rate: Decimal | None = None
    value_at_rate: Decimal | None = None


class AccountCreateIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=150)
    parent_id: uuid.UUID
    account_type: str | None = None
    is_group: bool = False
    currency: str | None = None
    description: str | None = Field(default=None, max_length=2000)


class AccountUpdateIn(BaseModel):
    version: int
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    parent_id: uuid.UUID | None = None
    account_type: str | None = None
    is_group: bool | None = None
    currency: str | None = None
    description: str | None = Field(default=None, max_length=2000)


class PeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    start_date: date
    end_date: date
    status: str
    closed_at: datetime | None


class PeriodActionIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class LineIn(BaseModel):
    account_id: uuid.UUID
    debit: Money = Decimal(0)
    credit: Money = Decimal(0)
    amount_in_currency: Decimal | None = Field(default=None, max_digits=38, decimal_places=18)
    exchange_rate: Decimal | None = Field(default=None, gt=0, max_digits=30, decimal_places=12)
    party_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=500)

    def to_service(self) -> service.LineIn:
        return service.LineIn(**self.model_dump())


class JournalIn(BaseModel):
    posting_date: date
    memo: str | None = Field(default=None, max_length=1000)
    lines: list[LineIn] = Field(min_length=2, max_length=500)


class OpeningBalancesIn(BaseModel):
    posting_date: date
    lines: list[LineIn] = Field(min_length=1, max_length=500)


class ReverseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class LineOut(BaseModel):
    line_no: int
    account_id: uuid.UUID
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    currency: str
    amount_in_currency: Decimal
    exchange_rate: Decimal
    party_id: uuid.UUID | None
    party_name: str | None = None
    project_id: uuid.UUID | None
    project_name: str | None = None
    employee_id: uuid.UUID | None
    employee_name: str | None = None
    description: str | None


class JournalOut(BaseModel):
    id: uuid.UUID
    number: str
    posting_date: date
    entry_type: str
    status: str
    source_type: str | None
    source_id: uuid.UUID | None
    source_number: str | None
    reversal_of_id: uuid.UUID | None
    reversed_by_id: uuid.UUID | None
    memo: str | None
    posted_at: datetime
    posted_by: uuid.UUID | None
    total: Decimal
    lines: list[LineOut] = []


class JournalPreviewOut(BaseModel):
    lines: list[LineOut]
    total_debit: Decimal
    total_credit: Decimal


# ---- accounts --------------------------------------------------------------------------------------


@router.get("/accounts/types")
async def account_types(_: CurrentUser = Depends(require("accounts.read"))) -> dict[str, list[str]]:
    return {k: list(v) for k, v in ACCOUNT_TYPES.items()}


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    as_of: date | None = None,
    include_inactive: bool = True,
    _: CurrentUser = Depends(require("accounts.read")),
    session: AsyncSession = Depends(get_session),
) -> list[AccountOut]:
    accounts = await service.list_accounts(session, include_inactive=include_inactive)
    raw = await service.balances(session, date_to=as_of)
    by_id = {a.id: a for a in accounts}
    totals: dict[uuid.UUID, Decimal] = {}
    base = await settings.base_currency(session)
    foreign = [a for a in accounts if not a.is_group and a.currency != base.code and a.id in raw]
    units = await service.unit_balances(session, account_ids=[a.id for a in foreign], date_to=as_of)
    on = as_of or await settings.today(session)
    rates: dict[str, Decimal | None] = {}
    for code in {a.currency for a in foreign}:
        try:
            rates[code] = (await settings.lookup_rate(session, code, base.code, on))[0]
        except NotFound:
            rates[code] = None

    totals: dict[uuid.UUID, Decimal] = {}
    valued: dict[uuid.UUID, Decimal] = {}  # at today's rates; book value where there is no rate
    own: dict[uuid.UUID, tuple[Decimal, Decimal | None, Decimal | None]] = {}
    for acc_id, (d, c) in raw.items():  # roll each leaf balance up to every ancestor
        leaf = by_id.get(acc_id)
        if leaf is None:
            continue
        amount = reports.signed(leaf.root_type, d, c)
        value = amount
        if acc_id in units:
            n = units[acc_id] if leaf.root_type in reports.DEBIT_NORMAL else -units[acc_id]
            rate = rates.get(leaf.currency)
            at_rate = quantize(n * rate, base.precision) if rate is not None else None
            own[acc_id] = (n, rate, at_rate)
            value = at_rate if at_rate is not None else amount
        for hexid in leaf.path.strip("/").split("/"):
            key = uuid.UUID(hexid)
            totals[key] = totals.get(key, Decimal(0)) + amount
            valued[key] = valued.get(key, Decimal(0)) + value
    out = []
    for a in service.tree_order(accounts):
        n, rate, at_rate = own.get(a.id, (None, None, None))
        if a.is_group and valued.get(a.id, Decimal(0)) != totals.get(a.id, Decimal(0)):
            at_rate = valued[a.id]
        out.append(
            AccountOut.model_validate(a).model_copy(
                update={
                    "depth": a.path.count("/") - 2,
                    "balance": totals.get(a.id, Decimal(0)),
                    "has_postings": a.id in raw,
                    "balance_in_currency": n,
                    "rate": rate,
                    "value_at_rate": at_rate,
                }
            )
        )
    return out


@router.post("/accounts", response_model=AccountOut, status_code=201)
async def create_account(
    body: AccountCreateIn,
    actor: CurrentUser = Depends(require("accounts.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    account = await service.create_account(session, actor_id=actor.id, **body.model_dump())
    await session.commit()
    return AccountOut.model_validate(account).model_copy(update={"depth": account.path.count("/") - 2})


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: uuid.UUID,
    body: AccountUpdateIn,
    actor: CurrentUser = Depends(require("accounts.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    account = await service.update_account(
        session,
        actor_id=actor.id,
        account_id=account_id,
        version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )
    await session.commit()
    return AccountOut.model_validate(account).model_copy(update={"depth": account.path.count("/") - 2})


@router.post("/accounts/{account_id}/{action}", response_model=AccountOut)
async def set_account_active(
    account_id: uuid.UUID,
    action: Literal["activate", "deactivate"],
    actor: CurrentUser = Depends(require("accounts.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    account = await service.set_account_active(
        session, actor_id=actor.id, account_id=account_id, active=action == "activate"
    )
    await session.commit()
    return AccountOut.model_validate(account).model_copy(update={"depth": account.path.count("/") - 2})


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: uuid.UUID,
    actor: CurrentUser = Depends(require("accounts.manage")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await service.delete_account(session, actor_id=actor.id, account_id=account_id)
    await session.commit()
    return Response(status_code=204)


# ---- periods ---------------------------------------------------------------------------------------


@router.get("/accounting-periods", response_model=list[PeriodOut])
async def list_periods(
    _: CurrentUser = Depends(require_any("periods.close", "reports.financial")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    periods = await service.list_periods(session)
    await session.commit()
    return periods


@router.post("/accounting-periods/{period_id}/close", response_model=PeriodOut)
async def close_period(
    period_id: uuid.UUID,
    body: PeriodActionIn,
    actor: CurrentUser = Depends(require("periods.close")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    period = await service.set_period_status(
        session, actor_id=actor.id, period_id=period_id, status="closed", reason=body.reason
    )
    await session.commit()
    return period


@router.post("/accounting-periods/{period_id}/reopen", response_model=PeriodOut)
async def reopen_period(
    period_id: uuid.UUID,
    body: PeriodActionIn,
    actor: CurrentUser = Depends(require("periods.reopen")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    if not body.reason:
        raise ValidationFailed("Reason required", errors=[field_error("reason", "Say why the period is reopened")])
    period = await service.set_period_status(
        session, actor_id=actor.id, period_id=period_id, status="open", reason=body.reason
    )
    await session.commit()
    return period


# ---- journal entries -------------------------------------------------------------------------------


async def _lines_out(session: AsyncSession, lines: list[Any]) -> list[LineOut]:
    """Accepts JournalLine rows or PreparedLine objects."""
    account_ids = {getattr(ln, "account_id", None) or ln.account.id for ln in lines}
    accounts = {a.id: a for a in (await session.execute(select(Account).where(Account.id.in_(account_ids)))).scalars()}

    def attr(ln: Any, name: str) -> Any:
        return getattr(ln.line, name) if hasattr(ln, "line") else getattr(ln, name)

    parties = await lookup.resolve(session, "party", (attr(ln, "party_id") for ln in lines))
    projects = await lookup.resolve(session, "project", (attr(ln, "project_id") for ln in lines))
    employees = await lookup.resolve(session, "employee", (attr(ln, "employee_id") for ln in lines))
    out = []
    for n, ln in enumerate(lines, start=1):
        prepared = hasattr(ln, "line")
        acc = ln.account if prepared else accounts[ln.account_id]
        party_id, project_id, employee_id = attr(ln, "party_id"), attr(ln, "project_id"), attr(ln, "employee_id")
        out.append(
            LineOut(
                line_no=n if prepared else ln.line_no,
                account_id=acc.id,
                account_code=acc.code,
                account_name=acc.name,
                debit=ln.debit if prepared else ln.debit_base,
                credit=ln.credit if prepared else ln.credit_base,
                currency=ln.currency,
                amount_in_currency=ln.amount_in_currency,
                exchange_rate=ln.exchange_rate,
                party_id=party_id,
                party_name=parties.get(party_id) if party_id else None,
                project_id=project_id,
                project_name=projects.get(project_id) if project_id else None,
                employee_id=employee_id,
                employee_name=employees.get(employee_id) if employee_id else None,
                description=attr(ln, "description"),
            )
        )
    return out


async def journal_out(session: AsyncSession, entry: JournalEntry, lines: list[JournalLine] | None) -> JournalOut:
    if lines is None:
        _, lines = await service.get_entry(session, entry.id)
    return JournalOut(
        id=entry.id,
        number=entry.number,
        posting_date=entry.posting_date,
        entry_type=entry.entry_type,
        status=entry.status,
        source_type=entry.source_type,
        source_id=entry.source_id,
        source_number=entry.source_number,
        reversal_of_id=entry.reversal_of_id,
        reversed_by_id=entry.reversed_by_id,
        memo=entry.memo,
        posted_at=entry.posted_at,
        posted_by=entry.posted_by,
        total=sum((ln.debit_base for ln in lines), Decimal(0)),
        lines=await _lines_out(session, lines),
    )


@router.get("/journal-entries", response_model=Page[JournalOut])
async def list_journal_entries(
    params: PageParams = Depends(page_params),
    entry_type: str | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    q: Annotated[str | None, Query(max_length=40)] = None,
    _: CurrentUser = Depends(require_any("journals.post", "reports.financial")),
    session: AsyncSession = Depends(get_session),
) -> Page[JournalOut]:
    stmt = select(JournalEntry).order_by(JournalEntry.posting_date.desc(), JournalEntry.number.desc())
    if entry_type:
        stmt = stmt.where(JournalEntry.entry_type == entry_type)
    if date_from:
        stmt = stmt.where(JournalEntry.posting_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.posting_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(JournalEntry.number.ilike(like) | JournalEntry.source_number.ilike(like))
    entries, total = await paginate(session, stmt, params)
    items = []
    for e in entries:
        _, lines = await service.get_entry(session, e.id)
        items.append(await journal_out(session, e, lines))
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.get("/journal-entries/{entry_id}", response_model=JournalOut)
async def get_journal_entry(
    entry_id: uuid.UUID,
    _: CurrentUser = Depends(require_any("journals.post", "reports.financial")),
    session: AsyncSession = Depends(get_session),
) -> JournalOut:
    entry, lines = await service.get_entry(session, entry_id)
    return await journal_out(session, entry, lines)


@router.post("/journal-entries/preview", response_model=JournalPreviewOut)
async def preview_journal(
    body: JournalIn, _: CurrentUser = Depends(require("journals.post")), session: AsyncSession = Depends(get_session)
) -> JournalPreviewOut:
    prepared = await service.prepare_lines(session, [ln.to_service() for ln in body.lines])
    return JournalPreviewOut(
        lines=await _lines_out(session, prepared),
        total_debit=sum(p.debit for p in prepared),
        total_credit=sum(p.credit for p in prepared),
    )


@router.post("/journal-entries", response_model=JournalOut, status_code=201)
async def post_manual_journal(
    body: JournalIn,
    request: Request,
    actor: CurrentUser = Depends(require("journals.post")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    async def action() -> JournalOut:
        entry = await service.post_journal(
            session,
            actor_id=actor.id,
            posting_date=body.posting_date,
            entry_type="manual",
            memo=body.memo,
            lines=[ln.to_service() for ln in body.lines],
        )
        return await journal_out(session, entry, None)

    return await run_idempotent(
        request, session, actor.id, body.model_dump(mode="json"), action, required=True, status_code=201
    )


@router.post("/journal-entries/{entry_id}/reverse", response_model=JournalOut)
async def reverse_journal(
    entry_id: uuid.UUID,
    body: ReverseIn,
    request: Request,
    actor: CurrentUser = Depends(require("journals.post")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    async def action() -> JournalOut:
        entry, _ = await service.get_entry(session, entry_id)
        if entry.source_type is not None:
            raise Conflict(f"This entry belongs to {entry.source_number or entry.source_type}; cancel that instead")
        reversal = await service.reverse_journal(
            session, actor_id=actor.id, journal_entry_id=entry_id, reason=body.reason
        )
        return await journal_out(session, reversal, None)

    return await run_idempotent(request, session, actor.id, body.model_dump(mode="json"), action, required=True)


@router.post("/opening-balances", response_model=JournalOut, status_code=201)
async def opening_balances(
    body: OpeningBalancesIn,
    request: Request,
    actor: CurrentUser = Depends(require("journals.post")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Post go-live balances; the difference goes to Opening Balance Equity automatically."""

    async def action() -> JournalOut:
        lines = [ln.to_service() for ln in body.lines]
        diff = sum((ln.debit - ln.credit for ln in lines), Decimal(0))
        if diff != 0:
            equity = await service.account_by_system_key(session, "opening_balance_equity")
            lines.append(
                service.LineIn(
                    account_id=equity.id,
                    debit=max(-diff, Decimal(0)),
                    credit=max(diff, Decimal(0)),
                    description="Opening balance offset",
                )
            )
        entry = await service.post_journal(
            session,
            actor_id=actor.id,
            posting_date=body.posting_date,
            entry_type="opening",
            memo="Opening balances",
            lines=lines,
        )
        return await journal_out(session, entry, None)

    return await run_idempotent(
        request, session, actor.id, body.model_dump(mode="json"), action, required=True, status_code=201
    )


# ---- reports ---------------------------------------------------------------------------------------


class TrialRowOut(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    root_type: str
    opening_debit: Decimal
    opening_credit: Decimal
    debit: Decimal
    credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal


class TrialBalanceOut(BaseModel):
    date_from: date
    date_to: date
    rows: list[TrialRowOut]
    totals: TrialRowOut | None


class StatementRow(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    depth: int
    is_group: bool
    amount: Decimal


class ProfitLossOut(BaseModel):
    date_from: date
    date_to: date
    income: list[StatementRow]
    expenses: list[StatementRow]
    total_income: Decimal
    total_expenses: Decimal
    net_profit: Decimal


class BalanceSheetOut(BaseModel):
    as_of: date
    assets: list[StatementRow]
    liabilities: list[StatementRow]
    equity: list[StatementRow]
    unclosed_earnings: Decimal
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    balanced: bool


class LedgerRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_id: uuid.UUID
    journal_entry_id: uuid.UUID
    number: str
    posting_date: date
    entry_type: str
    status: str
    source_type: str | None
    source_id: uuid.UUID | None
    source_number: str | None
    account_id: uuid.UUID
    account_code: str
    account_name: str
    description: str | None
    memo: str | None
    debit: Decimal
    credit: Decimal
    currency: str
    amount_in_currency: Decimal
    party_id: uuid.UUID | None
    party_name: str | None = None
    project_id: uuid.UUID | None
    project_name: str | None = None
    employee_id: uuid.UUID | None
    balance: Decimal | None


class LedgerOut(BaseModel):
    date_from: date
    date_to: date
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    total_debit: Decimal
    total_credit: Decimal
    rows: list[LedgerRowOut]
    truncated: bool


def _rows(tree: list[reports.TreeRow]) -> list[StatementRow]:
    return [
        StatementRow(
            account_id=r.account_id, code=r.code, name=r.name, depth=r.depth, is_group=r.is_group, amount=r.amount
        )
        for r in reports.flatten(tree)
    ]


def _check_range(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise ValidationFailed("Invalid range", errors=[field_error("to", "End date is before start date")])


Format = Literal["json", "csv"]
Report = Depends(require("reports.financial"))


@router.get("/reports/trial-balance", response_model=TrialBalanceOut)
async def trial_balance(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    format: Format = "json",
    _: CurrentUser = Report,
    session: AsyncSession = Depends(get_session),
) -> Any:
    _check_range(date_from, date_to)
    rows = [TrialRowOut(**r.__dict__) for r in await reports.trial_balance(session, date_from, date_to)]
    zero = Decimal(0)
    totals = TrialRowOut(
        account_id=uuid.UUID(int=0),
        code="",
        name="Total",
        root_type="",
        **{
            f: sum((getattr(r, f) for r in rows), zero)
            for f in ("opening_debit", "opening_credit", "debit", "credit", "closing_debit", "closing_credit")
        },
    )
    if format == "csv":
        fields = [
            "code",
            "name",
            "opening_debit",
            "opening_credit",
            "debit",
            "credit",
            "closing_debit",
            "closing_credit",
        ]
        return csv_response(
            f"trial-balance_{date_from}_{date_to}.csv",
            fields,
            ([getattr(r, f) for f in fields] for r in [*rows, totals]),
        )
    return TrialBalanceOut(date_from=date_from, date_to=date_to, rows=rows, totals=totals)


@router.get("/reports/profit-and-loss", response_model=ProfitLossOut)
async def profit_and_loss(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    project_id: uuid.UUID | None = None,
    format: Format = "json",
    _: CurrentUser = Report,
    session: AsyncSession = Depends(get_session),
) -> Any:
    _check_range(date_from, date_to)
    income, expense, ti, te = await reports.profit_and_loss(session, date_from, date_to, project_id)
    out = ProfitLossOut(
        date_from=date_from,
        date_to=date_to,
        income=_rows(income),
        expenses=_rows(expense),
        total_income=ti,
        total_expenses=te,
        net_profit=ti - te,
    )
    if format == "csv":
        lines = [("Income", "", "", "")] + [(r.code, "  " * r.depth + r.name, r.amount, "") for r in out.income]
        lines += [("", "Total income", ti, ""), ("Expenses", "", "", "")]
        lines += [(r.code, "  " * r.depth + r.name, r.amount, "") for r in out.expenses]
        lines += [("", "Total expenses", te, ""), ("", "Net profit", ti - te, "")]
        return csv_response(f"profit-and-loss_{date_from}_{date_to}.csv", ["code", "account", "amount", ""], lines)
    return out


class HoldingOut(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    account_type: str
    currency: str
    units: Decimal
    book_value: Decimal
    rate: Decimal | None
    rate_date: date | None
    market_value: Decimal | None


class CurrencyHoldingOut(BaseModel):
    currency: str
    units: Decimal
    book_value: Decimal
    rate: Decimal | None
    rate_date: date | None
    market_value: Decimal | None  # None when no saved rate exists for the currency
    accounts: list[HoldingOut]


class HoldingsOut(BaseModel):
    as_of: date
    base_currency: str
    currencies: list[CurrencyHoldingOut]
    book_total: Decimal
    market_total: Decimal  # currencies without a rate count at book value
    missing_rates: list[str]


@router.get("/reports/holdings", response_model=HoldingsOut)
async def holdings(
    as_of: date | None = None,
    format: Format = "json",
    _: CurrentUser = Report,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Cash, bank, wallets and cards grouped by currency: units held, recorded (book) value, and value at
    the saved exchange rate on `as_of` (default today). Display only; nothing is posted."""
    as_of = as_of or await settings.today(session)
    base = await settings.base_currency(session)
    rows = await reports.holdings(session, as_of)
    groups: dict[str, list[reports.Holding]] = {}
    for h in rows:
        groups.setdefault(h.currency, []).append(h)
    currencies = []
    for code, items in groups.items():
        units = sum((h.units for h in items), Decimal(0))
        book = sum((h.book_value for h in items), Decimal(0))
        first = items[0]
        currencies.append(
            CurrencyHoldingOut(
                currency=code,
                units=units,
                book_value=book,
                rate=first.rate,
                rate_date=first.rate_date,
                market_value=sum((h.market_value or Decimal(0) for h in items), Decimal(0))
                if first.rate is not None
                else None,
                accounts=[HoldingOut(**vars(h)) for h in items],
            )
        )
    # Base currency first, then by value.
    currencies.sort(key=lambda c: (c.currency != base.code, -(c.market_value or c.book_value)))
    book_total = sum((c.book_value for c in currencies), Decimal(0))
    market_total = sum((c.market_value if c.market_value is not None else c.book_value for c in currencies), Decimal(0))
    missing = [c.currency for c in currencies if c.market_value is None and c.units]
    if format == "csv":
        return csv_response(
            f"holdings_{as_of}.csv",
            ["currency", "account", "units", "book_value", "rate", "rate_date", "market_value"],
            [
                (c.currency, f"{h.code} {h.name}", h.units, h.book_value, h.rate, h.rate_date, h.market_value)
                for c in currencies
                for h in c.accounts
            ],
        )
    return HoldingsOut(
        as_of=as_of,
        base_currency=base.code,
        currencies=currencies,
        book_total=book_total,
        market_total=market_total,
        missing_rates=missing,
    )


@router.get("/reports/balance-sheet", response_model=BalanceSheetOut)
async def balance_sheet(
    as_of: date, format: Format = "json", _: CurrentUser = Report, session: AsyncSession = Depends(get_session)
) -> Any:
    bs = await reports.balance_sheet(session, as_of)
    out = BalanceSheetOut(
        as_of=as_of,
        assets=_rows(bs.assets),
        liabilities=_rows(bs.liabilities),
        equity=_rows(bs.equity),
        unclosed_earnings=bs.unclosed_earnings,
        total_assets=bs.total_assets,
        total_liabilities=bs.total_liabilities,
        total_equity=bs.total_equity,
        balanced=bs.balanced,
    )
    if format == "csv":
        lines: list[tuple[Any, ...]] = []
        for title, rows, total in (
            ("Assets", out.assets, out.total_assets),
            ("Liabilities", out.liabilities, out.total_liabilities),
            ("Equity", out.equity, None),
        ):
            lines.append((title, "", ""))
            lines += [(r.code, "  " * r.depth + r.name, r.amount) for r in rows]
            if total is not None:
                lines.append(("", f"Total {title.lower()}", total))
        lines += [
            ("", "Current earnings (not yet closed)", out.unclosed_earnings),
            ("", "Total equity", out.total_equity),
        ]
        return csv_response(f"balance-sheet_{as_of}.csv", ["code", "account", "amount"], lines)
    return out


@router.get("/reports/general-ledger", response_model=LedgerOut)
async def general_ledger(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    account_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = None,
    include_reversed: bool = False,
    format: Format = "json",
    _: CurrentUser = Report,
    session: AsyncSession = Depends(get_session),
) -> Any:
    _check_range(date_from, date_to)
    opening, rows, truncated = await reports.general_ledger(
        session,
        date_from=date_from,
        date_to=date_to,
        account_id=account_id,
        party_id=party_id,
        project_id=project_id,
        employee_id=employee_id,
        include_reversed=include_reversed,
    )
    parties = await lookup.resolve(session, "party", (r.party_id for r in rows))
    projects = await lookup.resolve(session, "project", (r.project_id for r in rows))
    out_rows = [
        LedgerRowOut.model_validate(r).model_copy(
            update={
                "party_name": parties.get(r.party_id) if r.party_id else None,
                "project_name": projects.get(r.project_id) if r.project_id else None,
            }
        )
        for r in rows
    ]
    total_debit = sum((r.debit for r in rows), Decimal(0))
    total_credit = sum((r.credit for r in rows), Decimal(0))
    closing = rows[-1].balance if rows and opening is not None else opening
    if format == "csv":
        fields = [
            "posting_date",
            "number",
            "source_number",
            "account_code",
            "account_name",
            "party_name",
            "project_name",
            "description",
            "debit",
            "credit",
            "balance",
        ]
        return csv_response(
            f"general-ledger_{date_from}_{date_to}.csv", fields, ([getattr(r, f) for f in fields] for r in out_rows)
        )
    return LedgerOut(
        date_from=date_from,
        date_to=date_to,
        opening_balance=opening,
        closing_balance=closing,
        total_debit=total_debit,
        total_credit=total_credit,
        rows=out_rows,
        truncated=truncated,
    )
