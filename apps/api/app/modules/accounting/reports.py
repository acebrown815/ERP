"""Financial statements computed from posted journal lines (the ledger is the source of truth)."""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting.models import DEBIT_NORMAL, Account, JournalEntry, JournalLine
from app.modules.accounting.service import ZERO, balances, list_accounts


def signed(root_type: str, debit: Decimal, credit: Decimal) -> Decimal:
    """Balance in the account's natural direction (debit-normal for assets/expenses)."""
    return debit - credit if root_type in DEBIT_NORMAL else credit - debit


@dataclass
class TreeRow:
    account_id: uuid.UUID
    code: str
    name: str
    root_type: str
    is_group: bool
    depth: int
    amount: Decimal = ZERO
    children: list["TreeRow"] = field(default_factory=list)


def build_tree(accounts: list[Account], amounts: dict[uuid.UUID, Decimal], roots: tuple[str, ...]) -> list[TreeRow]:
    """Ordered rows (depth-first by code) with group totals rolled up; zero-only branches are dropped."""
    by_parent: dict[uuid.UUID | None, list[Account]] = {}
    for a in accounts:
        if a.root_type in roots:
            by_parent.setdefault(a.parent_id, []).append(a)

    def walk(parent: uuid.UUID | None, depth: int) -> list[TreeRow]:
        rows = []
        for a in sorted(by_parent.get(parent, []), key=lambda x: x.code):
            row = TreeRow(a.id, a.code, a.name, a.root_type, a.is_group, depth, amounts.get(a.id, ZERO))
            row.children = walk(a.id, depth + 1)
            if a.is_group:
                row.amount = sum((c.amount for c in row.children), ZERO)
            if row.amount != 0 or any(c.amount != 0 for c in row.children):
                rows.append(row)
        return rows

    return walk(None, 0)


def flatten(rows: list[TreeRow]) -> list[TreeRow]:
    out: list[TreeRow] = []
    for r in rows:
        out.append(r)
        out.extend(flatten(r.children))
    return out


# ---- trial balance ---------------------------------------------------------------------------------


@dataclass
class TrialRow:
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


def _split(net: Decimal) -> tuple[Decimal, Decimal]:
    return (net, ZERO) if net >= 0 else (ZERO, -net)


async def trial_balance(session: AsyncSession, date_from: date, date_to: date) -> list[TrialRow]:
    accounts = {a.id: a for a in await list_accounts(session)}
    opening = await balances(session, date_to=date_from - timedelta(days=1))
    period = await balances(session, date_from=date_from, date_to=date_to)
    rows = []
    for acc_id in sorted(set(opening) | set(period), key=lambda i: accounts[i].code):
        a = accounts[acc_id]
        od, oc = opening.get(acc_id, (ZERO, ZERO))
        pd, pc = period.get(acc_id, (ZERO, ZERO))
        o_d, o_c = _split(od - oc)
        c_d, c_c = _split(od - oc + pd - pc)
        rows.append(TrialRow(a.id, a.code, a.name, a.root_type, o_d, o_c, pd, pc, c_d, c_c))
    return rows


# ---- profit & loss / balance sheet -----------------------------------------------------------------


async def profit_and_loss(
    session: AsyncSession, date_from: date, date_to: date, project_id: uuid.UUID | None = None
) -> tuple[list[TreeRow], list[TreeRow], Decimal, Decimal]:
    accounts = await list_accounts(session)
    roots = {a.id: a.root_type for a in accounts}
    raw = await balances(session, date_from=date_from, date_to=date_to, project_id=project_id)
    amounts = {k: signed(roots[k], d, c) for k, (d, c) in raw.items()}
    income = build_tree(accounts, amounts, ("income",))
    expense = build_tree(accounts, amounts, ("expense",))
    total_income = sum((r.amount for r in income), ZERO)
    total_expense = sum((r.amount for r in expense), ZERO)
    return income, expense, total_income, total_expense


@dataclass
class BalanceSheet:
    assets: list[TreeRow]
    liabilities: list[TreeRow]
    equity: list[TreeRow]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal  # includes unclosed earnings
    unclosed_earnings: Decimal

    @property
    def balanced(self) -> bool:
        return self.total_assets == self.total_liabilities + self.total_equity


async def balance_sheet(session: AsyncSession, as_of: date) -> BalanceSheet:
    accounts = await list_accounts(session)
    roots = {a.id: a.root_type for a in accounts}
    raw = await balances(session, date_to=as_of)
    amounts = {k: signed(roots[k], d, c) for k, (d, c) in raw.items()}
    earnings = sum(
        (v if roots[k] == "income" else -v for k, v in amounts.items() if roots[k] in ("income", "expense")), ZERO
    )
    assets = build_tree(accounts, amounts, ("asset",))
    liabilities = build_tree(accounts, amounts, ("liability",))
    equity = build_tree(accounts, amounts, ("equity",))
    total_a = sum((r.amount for r in assets), ZERO)
    total_l = sum((r.amount for r in liabilities), ZERO)
    total_e = sum((r.amount for r in equity), ZERO) + earnings
    return BalanceSheet(assets, liabilities, equity, total_a, total_l, total_e, earnings)


# ---- general ledger --------------------------------------------------------------------------------


@dataclass
class LedgerRow:
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
    project_id: uuid.UUID | None
    employee_id: uuid.UUID | None
    balance: Decimal | None = None


async def general_ledger(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    account_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = None,
    include_reversed: bool = False,
    limit: int = 2000,
) -> tuple[Decimal | None, list[LedgerRow], bool]:
    """Returns (opening balance for the account filter, rows with running balance, truncated?)."""
    account_filter = None
    opening: Decimal | None = None
    if account_id:
        root = (await session.execute(select(Account).where(Account.id == account_id))).scalar_one()
        account_filter = Account.path.startswith(root.path)
        sub_ids = list((await session.execute(select(Account.id).where(account_filter))).scalars())
        before = await balances(session, date_to=date_from - timedelta(days=1), account_ids=sub_ids)
        opening = sum((signed(root.root_type, d, c) for d, c in before.values()), ZERO)

    stmt = (
        select(JournalLine, JournalEntry, Account)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalEntry.posting_date >= date_from, JournalEntry.posting_date <= date_to)
        .order_by(JournalEntry.posting_date, JournalEntry.number, JournalLine.line_no)
        .limit(limit + 1)
    )
    if account_filter is not None:
        stmt = stmt.where(account_filter)
    if party_id:
        stmt = stmt.where(JournalLine.party_id == party_id)
    if project_id:
        stmt = stmt.where(JournalLine.project_id == project_id)
    if employee_id:
        stmt = stmt.where(JournalLine.employee_id == employee_id)
    if not include_reversed:
        # Hide cancelled pairs: both the reversed original and its reversal (they net to zero).
        stmt = stmt.where(JournalEntry.status == "posted", JournalEntry.reversal_of_id.is_(None))

    result = (await session.execute(stmt)).all()
    truncated = len(result) > limit
    rows: list[LedgerRow] = []
    running = opening
    for line, entry, acc in result[:limit]:
        if running is not None:
            running += signed(acc.root_type, line.debit_base, line.credit_base)
        rows.append(
            LedgerRow(
                line.id,
                entry.id,
                entry.number,
                entry.posting_date,
                entry.entry_type,
                entry.status,
                entry.source_type,
                entry.source_id,
                entry.source_number,
                acc.id,
                acc.code,
                acc.name,
                line.description,
                entry.memo,
                line.debit_base,
                line.credit_base,
                line.currency,
                line.amount_in_currency,
                line.party_id,
                line.project_id,
                line.employee_id,
                running,
            )
        )
    return opening, rows, truncated
