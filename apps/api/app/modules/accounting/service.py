import calendar
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.core.money import quantize
from app.core.numbering import next_number
from app.modules.accounting.chart import CATEGORY_DEFAULTS, DEFAULT_CHART
from app.modules.accounting.models import (
    ACCOUNT_TYPES,
    MONEY_ACCOUNT_TYPES,
    Account,
    AccountingPeriod,
    JournalEntry,
    JournalLine,
)
from app.modules.audit import api as audit
from app.modules.categories import api as categories
from app.modules.settings import api as settings

ZERO = Decimal(0)


# ---- accounts --------------------------------------------------------------------------------------


def _snapshot(a: Account) -> dict[str, Any]:
    return {
        "code": a.code,
        "name": a.name,
        "parent_id": a.parent_id,
        "account_type": a.account_type,
        "is_group": a.is_group,
        "currency": a.currency,
        "description": a.description,
        "is_active": a.is_active,
    }


async def account_subtree(session: AsyncSession, account_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """The accounts and, for groups, every account under them."""
    for account_id in account_ids:
        await get_account(session, account_id)
    children: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for aid, parent in (await session.execute(select(Account.id, Account.parent_id))).all():
        children.setdefault(parent, []).append(aid)
    out: set[uuid.UUID] = set()
    todo = list(account_ids)
    while todo:
        aid = todo.pop()
        if aid not in out:
            out.add(aid)
            todo.extend(children.get(aid, []))
    return list(out)


def entries_touching(account_ids: list[uuid.UUID]) -> Any:
    """Subquery: journal entries with a line on any of these accounts."""
    return select(JournalLine.journal_entry_id).where(JournalLine.account_id.in_(account_ids))


async def get_account(session: AsyncSession, account_id: uuid.UUID, *, lock: bool = False) -> Account:
    stmt = select(Account).where(Account.id == account_id)
    if lock:
        stmt = stmt.with_for_update()
    account = (await session.execute(stmt)).scalar_one_or_none()
    if account is None:
        raise NotFound("Account not found")
    return account


async def account_by_system_key(session: AsyncSession, key: str) -> Account:
    account = (await session.execute(select(Account).where(Account.system_key == key))).scalar_one_or_none()
    if account is None:
        raise NotFound(f"System account {key!r} is missing; run the seed command")
    return account


async def account_by_code(session: AsyncSession, code: str) -> Account | None:
    return (await session.execute(select(Account).where(Account.code == code))).scalar_one_or_none()


async def list_accounts(session: AsyncSession, *, include_inactive: bool = True) -> list[Account]:
    stmt = select(Account).order_by(Account.code)
    if not include_inactive:
        stmt = stmt.where(Account.is_active.is_(True))
    return list((await session.execute(stmt)).scalars())


def tree_order(accounts: list[Account]) -> list[Account]:
    """Depth-first, siblings by code: the order a chart of accounts is read in."""
    children: dict[uuid.UUID | None, list[Account]] = {}
    for a in accounts:
        children.setdefault(a.parent_id, []).append(a)
    ids = {a.id for a in accounts}
    out: list[Account] = []

    def walk(parent: uuid.UUID | None) -> None:
        for a in sorted(children.get(parent, []), key=lambda x: x.code):
            out.append(a)
            walk(a.id)

    walk(None)
    # Accounts whose parent was filtered out (e.g. inactive) still appear.
    out += sorted((a for a in accounts if a.parent_id is not None and a.parent_id not in ids), key=lambda x: x.code)
    return out


async def has_postings(session: AsyncSession, account_id: uuid.UUID) -> bool:
    return bool((await session.execute(select(exists().where(JournalLine.account_id == account_id)))).scalar_one())


async def _has_children(session: AsyncSession, account_id: uuid.UUID) -> bool:
    return bool((await session.execute(select(exists().where(Account.parent_id == account_id)))).scalar_one())


async def _check_code(session: AsyncSession, code: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(Account.id).where(Account.code == code)
    if exclude:
        stmt = stmt.where(Account.id != exclude)
    if (await session.execute(stmt)).first():
        raise ValidationFailed("Code in use", errors=[field_error("code", f"Account code {code} already exists")])


async def _check_currency(session: AsyncSession, code: str) -> None:
    try:
        cur = await settings.get_currency(session, code)
    except NotFound:
        cur = None
    if cur is None or not cur.is_active:
        raise ValidationFailed("Invalid currency", errors=[field_error("currency", "Must be an active currency")])


async def create_account(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    code: str,
    name: str,
    parent_id: uuid.UUID | None,
    account_type: str | None,
    is_group: bool,
    currency: str | None,
    description: str | None = None,
    root_type: str | None = None,
    system_key: str | None = None,
) -> Account:
    code = code.strip()
    await _check_code(session, code)
    if parent_id is not None:
        parent = await get_account(session, parent_id)
        if not parent.is_group:
            raise ValidationFailed("Invalid parent", errors=[field_error("parent_id", "Parent must be a group")])
        root = parent.root_type
    elif root_type in ACCOUNT_TYPES:
        parent, root = None, root_type
    else:
        raise ValidationFailed("Parent required", errors=[field_error("parent_id", "Choose a parent group")])

    account_type = account_type or ACCOUNT_TYPES[root][0 if root not in ("asset", "liability") else -1]
    if account_type not in ACCOUNT_TYPES[root]:
        allowed = ", ".join(ACCOUNT_TYPES[root])
        raise ValidationFailed("Invalid type", errors=[field_error("account_type", f"For {root}: {allowed}")])
    currency = (currency or (await settings.base_currency(session)).code).upper()
    await _check_currency(session, currency)

    account = Account(
        code=code,
        name=name.strip(),
        parent_id=parent_id,
        root_type=root,
        account_type=account_type,
        is_group=is_group,
        currency=currency,
        description=description,
        system_key=system_key,
        path="",
        created_by=actor_id,
        updated_by=actor_id,
    )
    session.add(account)
    await session.flush()
    account.path = f"{parent.path if parent else '/'}{account.id.hex}/"
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="account.created",
        entity_type="account",
        entity_id=account.id,
        after=_snapshot(account),
    )
    return account


async def update_account(
    session: AsyncSession, *, actor_id: uuid.UUID, account_id: uuid.UUID, version: int, changes: dict[str, Any]
) -> Account:
    account = await get_account(session, account_id, lock=True)
    if account.version != version:
        raise PreconditionFailed()
    before = _snapshot(account)
    posted = await has_postings(session, account.id)
    structural = {"parent_id", "is_group", "currency", "account_type"} & {
        k for k, v in changes.items() if v != getattr(account, k)
    }
    if account.system_key and structural - {"parent_id"}:
        raise Forbidden("System accounts can be renamed or moved, but their type cannot change")

    if "code" in changes and changes["code"] != account.code:
        await _check_code(session, changes["code"].strip(), exclude=account.id)
        account.code = changes["code"].strip()
    if "name" in changes:
        account.name = changes["name"].strip()
    if "description" in changes:
        account.description = changes["description"]

    if "is_group" in structural:
        if changes["is_group"] and posted:
            raise Conflict("An account with postings cannot become a group")
        if not changes["is_group"] and await _has_children(session, account.id):
            raise Conflict("A group with sub-accounts cannot become a posting account")
        account.is_group = changes["is_group"]
    if "currency" in structural:
        if posted:
            raise Conflict("Currency cannot change after postings exist")
        await _check_currency(session, changes["currency"].upper())
        account.currency = changes["currency"].upper()
    if "account_type" in structural:
        if changes["account_type"] not in ACCOUNT_TYPES[account.root_type]:
            raise ValidationFailed("Invalid type", errors=[field_error("account_type", "Not valid for this root")])
        if posted:
            raise Conflict("Type cannot change after postings exist")
        account.account_type = changes["account_type"]
    if "parent_id" in structural:
        await _move(session, account, changes["parent_id"])

    account.version += 1
    account.updated_by = actor_id
    await session.flush()
    b, a = audit.diff(before, _snapshot(account))
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="account.updated",
            entity_type="account",
            entity_id=account.id,
            before=b,
            after=a,
        )
    return account


async def _move(session: AsyncSession, account: Account, parent_id: uuid.UUID | None) -> None:
    if parent_id is None:
        raise ValidationFailed("Parent required", errors=[field_error("parent_id", "Choose a parent group")])
    parent = await get_account(session, parent_id)
    if not parent.is_group or parent.root_type != account.root_type:
        raise ValidationFailed(
            "Invalid parent", errors=[field_error("parent_id", "Parent must be a group of the same root type")]
        )
    if parent.path.startswith(account.path):
        raise ValidationFailed("Invalid parent", errors=[field_error("parent_id", "Cannot move under itself")])
    old_prefix, new_prefix = account.path, f"{parent.path}{account.id.hex}/"
    await session.execute(
        update(Account)
        .where(Account.path.startswith(old_prefix))
        .values(path=new_prefix + func.substr(Account.path, len(old_prefix) + 1))
        .execution_options(synchronize_session=False)
    )
    account.parent_id = parent.id
    account.path = new_prefix


async def set_account_active(
    session: AsyncSession, *, actor_id: uuid.UUID, account_id: uuid.UUID, active: bool
) -> Account:
    account = await get_account(session, account_id, lock=True)
    if account.is_active == active:
        return account
    if not active:
        if account.system_key:
            raise Forbidden("System accounts cannot be deactivated")
        active_children = (
            await session.execute(select(exists().where(Account.parent_id == account.id, Account.is_active.is_(True))))
        ).scalar_one()
        if active_children:
            raise Conflict("Deactivate its sub-accounts first")
        if not account.is_group:
            debit, credit = (await balances(session, account_ids=[account.id])).get(account.id, (ZERO, ZERO))
            if debit != credit:
                raise Conflict("Only accounts with a zero balance can be deactivated")
    account.is_active = active
    account.version += 1
    account.updated_by = actor_id
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="account.activated" if active else "account.deactivated",
        entity_type="account",
        entity_id=account.id,
    )
    return account


async def delete_account(session: AsyncSession, *, actor_id: uuid.UUID, account_id: uuid.UUID) -> None:
    account = await get_account(session, account_id, lock=True)
    if account.system_key:
        raise Forbidden("System accounts cannot be deleted")
    if await has_postings(session, account.id) or await _has_children(session, account.id):
        raise Conflict("Accounts with postings or sub-accounts cannot be deleted; deactivate instead")
    snapshot = _snapshot(account)
    try:
        async with session.begin_nested():
            await session.delete(account)
            await session.flush()
    except IntegrityError as exc:
        raise Conflict("Account is referenced elsewhere (for example by a payment account)") from exc
    await audit.record(
        session,
        actor_id=actor_id,
        action="account.deleted",
        entity_type="account",
        entity_id=account_id,
        before=snapshot,
    )


# ---- periods ---------------------------------------------------------------------------------------


def month_bounds(on: date) -> tuple[date, date]:
    return on.replace(day=1), on.replace(day=calendar.monthrange(on.year, on.month)[1])


async def ensure_period(session: AsyncSession, on: date) -> AccountingPeriod:
    start, end = month_bounds(on)
    await session.execute(
        insert(AccountingPeriod)
        .values(id=uuid.uuid4(), start_date=start, end_date=end, status="open")
        .on_conflict_do_nothing(index_elements=["start_date"])
    )
    return (await session.execute(select(AccountingPeriod).where(AccountingPeriod.start_date == start))).scalar_one()


async def list_periods(session: AsyncSession) -> list[AccountingPeriod]:
    await ensure_period(session, date.today())
    return list(
        (await session.execute(select(AccountingPeriod).order_by(AccountingPeriod.start_date.desc()))).scalars()
    )


async def set_period_status(
    session: AsyncSession, *, actor_id: uuid.UUID, period_id: uuid.UUID, status: str, reason: str | None = None
) -> AccountingPeriod:
    period = (
        await session.execute(select(AccountingPeriod).where(AccountingPeriod.id == period_id).with_for_update())
    ).scalar_one_or_none()
    if period is None:
        raise NotFound("Period not found")
    if period.status == status:
        return period
    if status == "closed" and period.end_date >= date.today():
        raise ValidationFailed("Period not over", errors=[field_error("status", "Only past periods can be closed")])
    period.status = status
    period.closed_at = datetime.now(UTC) if status == "closed" else None
    period.closed_by = actor_id if status == "closed" else None
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action=f"period.{'closed' if status == 'closed' else 'reopened'}",
        entity_type="accounting_period",
        entity_id=period.id,
        after={"start_date": period.start_date, "reason": reason},
    )
    return period


# ---- posting ---------------------------------------------------------------------------------------


@dataclass
class LineIn:
    account_id: uuid.UUID
    debit: Decimal = ZERO  # base currency
    credit: Decimal = ZERO  # base currency
    amount_in_currency: Decimal | None = None  # signed, account currency; required for non-base accounts
    exchange_rate: Decimal | None = None
    party_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    description: str | None = None


@dataclass
class PreparedLine:
    line: LineIn
    account: Account
    debit: Decimal
    credit: Decimal
    currency: str
    amount_in_currency: Decimal
    exchange_rate: Decimal


async def prepare_lines(
    session: AsyncSession, lines: list[LineIn], *, allow_inactive: bool = False
) -> list[PreparedLine]:
    """Validate and normalize lines without writing anything (also used for posting previews)."""
    base = await settings.base_currency(session)
    errors: list[dict[str, Any]] = []
    if len(lines) < 2:
        raise ValidationFailed(
            "A journal entry needs at least two lines",
            errors=[field_error("lines", "Add at least two lines", "too_few")],
        )

    ids = {ln.account_id for ln in lines}
    accounts = {a.id: a for a in (await session.execute(select(Account).where(Account.id.in_(ids)))).scalars()}
    prepared: list[PreparedLine] = []
    for i, ln in enumerate(lines):
        debit, credit = quantize(ln.debit, base.precision), quantize(ln.credit, base.precision)
        account = accounts.get(ln.account_id)
        if account is None:
            errors.append(field_error(f"lines.{i}.account_id", "Unknown account"))
            continue
        if account.is_group or not (account.is_active or allow_inactive):
            errors.append(field_error(f"lines.{i}.account_id", f"{account.code} is a group or inactive"))
            continue
        if debit < 0 or credit < 0 or (debit == 0) == (credit == 0):
            errors.append(field_error(f"lines.{i}", "Enter either a debit or a credit (positive)", "one_sided"))
            continue
        if account.currency == base.code:
            amount, rate = debit - credit, Decimal(1)
        else:
            cur = await settings.get_currency(session, account.currency)
            if ln.amount_in_currency is None or not ln.exchange_rate or ln.exchange_rate <= 0:
                errors.append(
                    field_error(
                        f"lines.{i}.amount_in_currency",
                        f"{account.code} is in {account.currency}: enter the amount and rate",
                    )
                )
                continue
            amount, rate = quantize(ln.amount_in_currency, cur.precision), ln.exchange_rate
            if amount == 0 or (amount > 0) != (debit > 0):
                errors.append(field_error(f"lines.{i}.amount_in_currency", "Sign must match debit/credit"))
                continue
        prepared.append(PreparedLine(ln, account, debit, credit, account.currency, amount, rate))
    if errors:
        raise ValidationFailed("Invalid journal lines", errors=errors)

    total_debit = sum((p.debit for p in prepared), ZERO)
    total_credit = sum((p.credit for p in prepared), ZERO)
    if total_debit != total_credit:
        raise ValidationFailed(
            f"Debits ({total_debit}) and credits ({total_credit}) must be equal",
            errors=[field_error("lines", f"Out of balance by {total_debit - total_credit}", "unbalanced")],
        )
    return prepared


async def post_journal(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    posting_date: date,
    entry_type: str,
    lines: list[LineIn],
    memo: str | None = None,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    source_number: str | None = None,
    reversal_of_id: uuid.UUID | None = None,
) -> JournalEntry:
    """The only way to write to the ledger. The caller owns the transaction."""
    # Reversals may hit accounts deactivated since the original posting (the DB trigger allows this too).
    prepared = await prepare_lines(session, lines, allow_inactive=entry_type == "reversal")
    period = await ensure_period(session, posting_date)
    if period.status != "open":
        raise ValidationFailed(
            f"The accounting period {period.start_date:%B %Y} is closed",
            errors=[field_error("posting_date", "Period is closed; reopen it or choose another date", "closed")],
        )
    entry = JournalEntry(
        number=await next_number(session, "JE", posting_date),
        posting_date=posting_date,
        period_id=period.id,
        entry_type=entry_type,
        source_type=source_type,
        source_id=source_id,
        source_number=source_number,
        memo=memo,
        posted_at=datetime.now(UTC),
        posted_by=actor_id,
        reversal_of_id=reversal_of_id,
    )
    session.add(entry)
    await session.flush()
    session.add_all(
        JournalLine(
            journal_entry_id=entry.id,
            line_no=n,
            account_id=p.account.id,
            debit_base=p.debit,
            credit_base=p.credit,
            currency=p.currency,
            amount_in_currency=p.amount_in_currency,
            exchange_rate=p.exchange_rate,
            party_id=p.line.party_id,
            project_id=p.line.project_id,
            employee_id=p.line.employee_id,
            category_id=p.line.category_id,
            description=p.line.description,
        )
        for n, p in enumerate(prepared, start=1)
    )
    await session.flush()
    await settings.lock_base_currency(session)
    total = sum((p.debit for p in prepared), ZERO)
    await audit.record(
        session,
        actor_id=actor_id,
        action="journal_entry.posted",
        entity_type="journal_entry",
        entity_id=entry.id,
        after={
            "number": entry.number,
            "entry_type": entry_type,
            "posting_date": posting_date,
            "total": total,
            "source": source_number,
        },
    )
    return entry


async def reverse_journal(
    session: AsyncSession, *, actor_id: uuid.UUID | None, journal_entry_id: uuid.UUID, reason: str
) -> JournalEntry:
    """Mirror an entry on its original date, so the pair nets to zero in every report (Section 6.4)."""
    original = (
        await session.execute(select(JournalEntry).where(JournalEntry.id == journal_entry_id).with_for_update())
    ).scalar_one_or_none()
    if original is None:
        raise NotFound("Journal entry not found")
    if original.status != "posted" or original.entry_type == "reversal":
        raise Conflict("This entry is already reversed or is itself a reversal")
    lines = (
        await session.execute(
            select(JournalLine).where(JournalLine.journal_entry_id == original.id).order_by(JournalLine.line_no)
        )
    ).scalars()
    mirrored = [
        LineIn(
            account_id=ln.account_id,
            debit=ln.credit_base,
            credit=ln.debit_base,
            amount_in_currency=-ln.amount_in_currency,
            exchange_rate=ln.exchange_rate,
            party_id=ln.party_id,
            project_id=ln.project_id,
            employee_id=ln.employee_id,
            category_id=ln.category_id,
            description=ln.description,
        )
        for ln in lines
    ]
    reversal = await post_journal(
        session,
        actor_id=actor_id,
        posting_date=original.posting_date,
        entry_type="reversal",
        lines=mirrored,
        memo=f"Reversal of {original.number}: {reason}",
        source_type=original.source_type,
        source_id=original.source_id,
        source_number=original.source_number,
        reversal_of_id=original.id,
    )
    original.status = "reversed"
    original.reversed_by_id = reversal.id
    await session.flush()
    return reversal


# ---- balances & reads ------------------------------------------------------------------------------


async def balances(
    session: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    account_ids: list[uuid.UUID] | None = None,
    project_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """Sum of posted debits and credits per account (base currency)."""
    stmt = (
        select(JournalLine.account_id, func.sum(JournalLine.debit_base), func.sum(JournalLine.credit_base))
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .group_by(JournalLine.account_id)
    )
    if date_from:
        stmt = stmt.where(JournalEntry.posting_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.posting_date <= date_to)
    if account_ids is not None:
        stmt = stmt.where(JournalLine.account_id.in_(account_ids))
    if project_id:
        stmt = stmt.where(JournalLine.project_id == project_id)
    return {acc: (d or ZERO, c or ZERO) for acc, d, c in (await session.execute(stmt)).all()}


async def unit_balances(
    session: AsyncSession, *, account_ids: list[uuid.UUID], date_to: date | None = None
) -> dict[uuid.UUID, Decimal]:
    """Net amount per account in the account's own currency (debit-positive), from posted lines."""
    if not account_ids:
        return {}
    stmt = (
        select(JournalLine.account_id, func.sum(JournalLine.amount_in_currency))
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalLine.account_id.in_(account_ids))
        .group_by(JournalLine.account_id)
    )
    if date_to:
        stmt = stmt.where(JournalEntry.posting_date <= date_to)
    return {acc: units or ZERO for acc, units in (await session.execute(stmt)).all()}


async def carrying_rate(session: AsyncSession, account_id: uuid.UUID, on: date) -> Decimal | None:
    """Average cost (base per unit) of what a foreign-currency or crypto account holds on `on`.

    Used to value money leaving such an account, so the realized gain/loss is booked and the account's
    base value goes to zero when its units do. None when the account holds no units.
    """
    units, value = (
        await session.execute(
            select(func.sum(JournalLine.amount_in_currency), func.sum(JournalLine.debit_base - JournalLine.credit_base))
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
            .where(JournalLine.account_id == account_id, JournalEntry.posting_date <= on)
        )
    ).one()
    if not units or units <= 0 or value is None:
        return None
    return value / units


async def get_entry(session: AsyncSession, entry_id: uuid.UUID) -> tuple[JournalEntry, list[JournalLine]]:
    entry = await session.get(JournalEntry, entry_id)
    if entry is None:
        raise NotFound("Journal entry not found")
    lines = list(
        (
            await session.execute(
                select(JournalLine).where(JournalLine.journal_entry_id == entry.id).order_by(JournalLine.line_no)
            )
        ).scalars()
    )
    return entry, lines


# ---- seed ------------------------------------------------------------------------------------------


async def _seed_hire_fees(session: AsyncSession) -> int:
    """Add the hired manager fees account to a chart created before it existed, on the next free 57xx code."""
    accounts = await list_accounts(session)
    if any(a.system_key == "hire_fees" for a in accounts):
        return 0
    taken = {a.code for a in accounts}
    code = next(c for c in map(str, range(5700, 5800)) if c not in taken)
    parent = next((a for a in accounts if a.code == "5000"), None)
    await create_account(
        session,
        actor_id=None,
        code=code,
        name="Hired Manager Fees",
        parent_id=parent.id if parent else None,
        account_type="expense",
        is_group=False,
        currency=None,
        root_type="expense",
        system_key="hire_fees",
    )
    return 1


async def seed(session: AsyncSession) -> int:
    """Create the default chart if no accounts exist, and default accounts on built-in categories."""
    created = 0
    if not (await session.execute(select(exists().where(Account.id.is_not(None))))).scalar_one():
        by_code: dict[str, Account] = {}
        for spec in DEFAULT_CHART:
            parent = by_code[spec.parent] if spec.parent else None
            by_code[spec.code] = await create_account(
                session,
                actor_id=None,
                code=spec.code,
                name=spec.name,
                parent_id=parent.id if parent else None,
                account_type=spec.account_type,
                is_group=spec.is_group,
                currency=spec.currency,
                root_type=spec.root_type,
                system_key=spec.system_key,
            )
            created += 1
    created += await _seed_hire_fees(session)
    codes = {a.code: a.id for a in await list_accounts(session)}
    for group, key, config_key, code in CATEGORY_DEFAULTS:
        if code in codes:
            await categories.set_config_default(session, group, key, config_key, str(codes[code]))
    return created


@dataclass
class ProjectLedger:
    income: Decimal = ZERO  # credit - debit on income accounts
    expenses: Decimal = ZERO  # debit - credit on expense accounts, excluding salaries
    salary: Decimal = ZERO  # debit - credit on the salary expense account


async def project_ledger(
    session: AsyncSession, project_ids: list[uuid.UUID], *, date_from: date | None = None, date_to: date | None = None
) -> dict[uuid.UUID, ProjectLedger]:
    """Income, direct expenses and salary cost per project, from posted lines tagged with the project."""
    out = {p: ProjectLedger() for p in project_ids}
    if not project_ids:
        return out
    stmt = (
        select(
            JournalLine.project_id,
            Account.root_type,
            Account.system_key,
            func.sum(JournalLine.debit_base),
            func.sum(JournalLine.credit_base),
        )
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(JournalLine.project_id.in_(project_ids), Account.root_type.in_(("income", "expense")))
        .group_by(JournalLine.project_id, Account.root_type, Account.system_key)
    )
    if date_from:
        stmt = stmt.where(JournalEntry.posting_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.posting_date <= date_to)
    for pid, root_type, system_key, d, c in (await session.execute(stmt)).all():
        row = out[pid]
        if root_type == "income":
            row.income += (c or ZERO) - (d or ZERO)
        elif system_key == "salary_expense":
            row.salary += (d or ZERO) - (c or ZERO)
        else:
            row.expenses += (d or ZERO) - (c or ZERO)
    return out


async def project_last_income(session: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, date]:
    """The latest date each project received income. Cancelled receipts don't count."""
    if not project_ids:
        return {}
    stmt = (
        select(JournalLine.project_id, func.max(JournalEntry.posting_date))
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(
            JournalLine.project_id.in_(project_ids),
            Account.root_type == "income",
            JournalLine.credit_base > 0,
            JournalEntry.reversed_by_id.is_(None),
        )
        .group_by(JournalLine.project_id)
    )
    return {pid: day for pid, day in (await session.execute(stmt)).all()}


@dataclass
class CategoryTotal:
    account_id: uuid.UUID
    code: str
    name: str
    category_id: uuid.UUID | None
    amount: Decimal  # natural sign: income credit - debit, expense debit - credit
    lines: int


async def category_totals(
    session: AsyncSession, *, root_type: str, date_from: date, date_to: date
) -> list[CategoryTotal]:
    """Income or expense per account and category over a date range (posted lines; reversals cancel out)."""
    stmt = (
        select(
            Account.id,
            Account.code,
            Account.name,
            JournalLine.category_id,
            func.sum(JournalLine.debit_base),
            func.sum(JournalLine.credit_base),
            func.count(),
        )
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(Account.root_type == root_type, JournalEntry.posting_date.between(date_from, date_to))
        .group_by(Account.id, Account.code, Account.name, JournalLine.category_id)
        .order_by(Account.code)
    )
    out = []
    for aid, code, name, cat, d, c, n in (await session.execute(stmt)).all():
        amount = (c or ZERO) - (d or ZERO) if root_type == "income" else (d or ZERO) - (c or ZERO)
        if amount:
            out.append(CategoryTotal(aid, code, name, cat, amount, n))
    return out


@dataclass
class PeriodTotals:
    income: Decimal = ZERO
    expenses: Decimal = ZERO  # excluding salaries
    salary: Decimal = ZERO

    @property
    def profit(self) -> Decimal:
        return self.income - self.expenses - self.salary


async def period_totals(session: AsyncSession, date_from: date, date_to: date) -> PeriodTotals:
    stmt = (
        select(
            Account.root_type, Account.system_key, func.sum(JournalLine.debit_base), func.sum(JournalLine.credit_base)
        )
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(Account.root_type.in_(("income", "expense")), JournalEntry.posting_date.between(date_from, date_to))
        .group_by(Account.root_type, Account.system_key)
    )
    out = PeriodTotals()
    for root_type, key, d, c in (await session.execute(stmt)).all():
        if root_type == "income":
            out.income += (c or ZERO) - (d or ZERO)
        elif key == "salary_expense":
            out.salary += (d or ZERO) - (c or ZERO)
        else:
            out.expenses += (d or ZERO) - (c or ZERO)
    return out


# ---- analysis: daily rows that reports bucket into salary periods ----------------------------------


@dataclass
class PLDay:
    """Income or expense posted on one day to one account / category / project, in the natural direction."""

    day: date
    root_type: str
    system_key: str | None
    account_id: uuid.UUID
    code: str
    name: str
    category_id: uuid.UUID | None
    project_id: uuid.UUID | None
    amount: Decimal  # income: credit - debit; expense: debit - credit


async def pl_by_day(
    session: AsyncSession, date_from: date, date_to: date, *, project_ids: list[uuid.UUID] | None = None
) -> list[PLDay]:
    stmt = (
        select(
            JournalEntry.posting_date,
            Account.root_type,
            Account.system_key,
            Account.id,
            Account.code,
            Account.name,
            JournalLine.category_id,
            JournalLine.project_id,
            func.sum(JournalLine.debit_base),
            func.sum(JournalLine.credit_base),
        )
        .join(Account, Account.id == JournalLine.account_id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(Account.root_type.in_(("income", "expense")), JournalEntry.posting_date.between(date_from, date_to))
        .group_by(
            JournalEntry.posting_date,
            Account.root_type,
            Account.system_key,
            Account.id,
            Account.code,
            Account.name,
            JournalLine.category_id,
            JournalLine.project_id,
        )
    )
    if project_ids is not None:
        stmt = stmt.where(JournalLine.project_id.in_(project_ids))
    out = []
    for day, root, key, aid, code, name, cat, proj, d, c in (await session.execute(stmt)).all():
        amount = (c or ZERO) - (d or ZERO) if root == "income" else (d or ZERO) - (c or ZERO)
        if amount:
            out.append(PLDay(day, root, key, aid, code, name, cat, proj, amount))
    return out


async def cash_balance(session: AsyncSession, on: date) -> Decimal:
    """Book value (as recorded, base currency) of all money accounts at the end of `on`."""
    value = await session.scalar(
        select(func.sum(JournalLine.debit_base - JournalLine.credit_base))
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(Account.account_type.in_(MONEY_ACCOUNT_TYPES), JournalEntry.posting_date <= on)
    )
    return value or ZERO


CASH_FLOW_KINDS = ("income", "expense", "salary", "equity", "other")


async def cash_flows(session: AsyncSession, date_from: date, date_to: date) -> list[tuple[date, dict[str, Decimal]]]:
    """Money moved per journal entry, split by what was on the other side, base currency.

    For each entry that touches a money account (bank, cash, wallet, card), the other lines say where the
    money came from or went: income, expense (salary separately), equity (owner capital and drawings) or
    other (loans, other assets). Signed as money in = positive, so the parts add up to the change in money
    accounts. A transfer between our own accounts cancels out, apart from any fee or exchange difference."""
    is_money = Account.account_type.in_(MONEY_ACCOUNT_TYPES)
    kind = case(
        (is_money, "money"),
        (Account.system_key == "salary_expense", "salary"),
        (Account.root_type.in_(("income", "expense", "equity")), Account.root_type),
        else_="other",
    )
    stmt = (
        select(
            JournalEntry.id, JournalEntry.posting_date, kind, func.sum(JournalLine.debit_base - JournalLine.credit_base)
        )
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalEntry.posting_date.between(date_from, date_to))
        .group_by(JournalEntry.id, JournalEntry.posting_date, kind)
    )
    entries: dict[uuid.UUID, tuple[date, dict[str, Decimal]]] = {}
    for entry_id, day, k, net in (await session.execute(stmt)).all():
        entries.setdefault(entry_id, (day, {}))[1][k] = net or ZERO
    out = []
    for day, parts in entries.values():
        if "money" not in parts:
            continue  # no money moved (accruals, reclassifications)
        # The counter lines' debit-minus-credit, negated, is the money that came in through them.
        out.append((day, {k: -parts.get(k, ZERO) for k in CASH_FLOW_KINDS}))
    return out
