import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.core.db import get_session
from app.core.errors import NotFound, ValidationFailed
from app.core.exports import Format, export_response
from app.core.idempotency import run_idempotent
from app.core.pagination import Page, PageParams, page_params, paginate
from app.modules.accounting import api as accounting
from app.modules.attribution import api as attribution
from app.modules.auth.api import CurrentUser, require, require_any
from app.modules.employees import api as employees
from app.modules.payments import service
from app.modules.payments.models import PaymentAccount, PaymentEntry
from app.modules.projects import api as projects
from app.modules.settings import api as settings

router = APIRouter(tags=["payments"])

Direction = Literal["receive", "pay", "internal_transfer"]
Quantity = Annotated[Decimal, Field(max_digits=38, decimal_places=18)]
Rate = Annotated[Decimal, Field(gt=0, max_digits=30, decimal_places=12)]
ReadPayments = Depends(require_any("payments.create", "reports.financial"))
# Employees (own salary or revenue) may read the payments that involve them; see _own_employee.
ReadOwnPayments = Depends(
    require_any("payments.create", "reports.financial", "salary.read", "revenue.read", "payments.read_own")
)
# What restricted access doesn't show on their own payments: internal notes, our accounts, who is charged.
HIRE_HIDDEN = {
    "category_id": None,
    "category_other_text": None,
    "paid_from_payment_account_id": None,
    "paid_to_payment_account_id": None,
    "counter_account_id": None,
    "exchange_rate": None,
    "fee_amount": Decimal(0),
    "eligible_amount_base": None,
    "employee_id": None,
    "employee_name": None,
    "description": None,
    "journal_entry_id": None,
    "reversal_journal_entry_id": None,
    "amended_from_id": None,
    "submitted_by": None,
    "created_by": None,
    "reconciled_at": None,
}
HIRE_HIDDEN_COLUMNS = {"employees", "fee_amount", "fee_paid_by", "description", "your_share"}


# ---- payment accounts ------------------------------------------------------------------------------


class PaymentAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    account_id: uuid.UUID
    kind: str
    currency: str
    details: dict[str, Any]
    notes: str | None
    is_active: bool
    version: int
    account_code: str | None = None
    account_name: str | None = None


class PaymentAccountCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    account_id: uuid.UUID
    details: dict[str, str] = {}
    notes: str | None = Field(default=None, max_length=2000)


class PaymentAccountUpdateIn(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=120)
    details: dict[str, str] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


def _mask(details: dict[str, Any]) -> dict[str, Any]:
    """Account numbers and wallet addresses are shown in full only to people who manage them."""
    return {k: (f"•••• {v[-4:]}" if isinstance(v, str) and len(v) > 6 else v) for k, v in details.items()}


async def _pa_out(session: AsyncSession, pa: PaymentAccount, user: CurrentUser) -> PaymentAccountOut:
    account = await accounting.get_account(session, pa.account_id)
    out = PaymentAccountOut.model_validate(pa).model_copy(
        update={"account_code": account.code, "account_name": account.name}
    )
    if not user.can("payment_accounts.manage"):
        out.details = _mask(out.details)
    return out


@router.get("/payment-accounts", response_model=list[PaymentAccountOut])
async def list_payment_accounts(
    include_inactive: bool = False,
    user: CurrentUser = Depends(require_any("payments.create", "payment_accounts.manage", "reports.financial")),
    session: AsyncSession = Depends(get_session),
) -> list[PaymentAccountOut]:
    return [
        await _pa_out(session, pa, user)
        for pa in await service.list_payment_accounts(session, include_inactive=include_inactive)
    ]


@router.post("/payment-accounts", response_model=PaymentAccountOut, status_code=201)
async def create_payment_account(
    body: PaymentAccountCreateIn,
    user: CurrentUser = Depends(require("payment_accounts.manage")),
    session: AsyncSession = Depends(get_session),
) -> PaymentAccountOut:
    pa = await service.create_payment_account(session, actor_id=user.id, **body.model_dump())
    await session.commit()
    return await _pa_out(session, pa, user)


@router.patch("/payment-accounts/{pa_id}", response_model=PaymentAccountOut)
async def update_payment_account(
    pa_id: uuid.UUID,
    body: PaymentAccountUpdateIn,
    user: CurrentUser = Depends(require("payment_accounts.manage")),
    session: AsyncSession = Depends(get_session),
) -> PaymentAccountOut:
    pa = await service.update_payment_account(
        session,
        actor_id=user.id,
        pa_id=pa_id,
        version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )
    await session.commit()
    return await _pa_out(session, pa, user)


# ---- payment entries: schemas ----------------------------------------------------------------------


class SplitRow(BaseModel):
    employee_id: uuid.UUID
    percent: Decimal | None = Field(default=None, gt=0, le=100, max_digits=7, decimal_places=4)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4)
    project_id: uuid.UUID | None = None

    def to_service(self) -> attribution.SplitIn:
        return attribution.SplitIn(**self.model_dump())


class EntryFields(BaseModel):
    posting_date: date
    direction: Direction
    party_id: uuid.UUID | None = None
    method_category_id: uuid.UUID | None = None
    method_other_text: str | None = Field(default=None, max_length=120)
    purpose_category_id: uuid.UUID | None = None
    purpose_other_text: str | None = Field(default=None, max_length=120)
    category_id: uuid.UUID | None = None
    category_other_text: str | None = Field(default=None, max_length=120)
    paid_from_payment_account_id: uuid.UUID | None = None
    paid_to_payment_account_id: uuid.UUID | None = None
    counter_account_id: uuid.UUID | None = None
    amount: Quantity = Field(gt=0)
    # Leave empty to use the saved rate for the date (Settings → Currencies & Rates).
    exchange_rate: Rate | None = None
    received_amount: Quantity | None = None
    received_exchange_rate: Rate | None = None
    fee_amount: Quantity = Field(default=Decimal(0), ge=0)
    fee_paid_by: Literal["client", "company"] = "company"
    project_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    # Salary payments only: the period this pays first (default: the oldest unpaid one).
    salary_period_id: uuid.UUID | None = None
    reference_no: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class EntryCreateIn(EntryFields):
    allocations: list[SplitRow] | None = Field(default=None, max_length=50)


class EntryUpdateIn(BaseModel):
    version: int
    posting_date: date | None = None
    direction: Direction | None = None
    party_id: uuid.UUID | None = None
    method_category_id: uuid.UUID | None = None
    method_other_text: str | None = Field(default=None, max_length=120)
    purpose_category_id: uuid.UUID | None = None
    purpose_other_text: str | None = Field(default=None, max_length=120)
    category_id: uuid.UUID | None = None
    category_other_text: str | None = Field(default=None, max_length=120)
    paid_from_payment_account_id: uuid.UUID | None = None
    paid_to_payment_account_id: uuid.UUID | None = None
    counter_account_id: uuid.UUID | None = None
    amount: Quantity | None = Field(default=None, gt=0)
    exchange_rate: Rate | None = None
    received_amount: Quantity | None = None
    received_exchange_rate: Rate | None = None
    fee_amount: Quantity | None = Field(default=None, ge=0)
    fee_paid_by: Literal["client", "company"] | None = None
    project_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    # Salary payments only: the period this pays first (default: the oldest unpaid one).
    salary_period_id: uuid.UUID | None = None
    reference_no: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    allocations: list[SplitRow] | None = Field(default=None, max_length=50)


class AllocationOut(BaseModel):
    employee_id: uuid.UUID
    employee_name: str | None
    project_id: uuid.UUID | None
    method: str
    percent: Decimal | None
    amount: Decimal | None
    status: str


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Employee view only: their share of a payment split between employees (base currency).
    my_share: Decimal | None = None
    id: uuid.UUID
    number: str
    posting_date: date
    direction: str
    status: str
    party_id: uuid.UUID | None
    method_category_id: uuid.UUID | None
    method_other_text: str | None
    purpose_category_id: uuid.UUID | None
    purpose_other_text: str | None
    category_id: uuid.UUID | None
    category_other_text: str | None
    paid_from_payment_account_id: uuid.UUID | None
    paid_to_payment_account_id: uuid.UUID | None
    counter_account_id: uuid.UUID | None
    amount: Decimal
    currency: str
    exchange_rate: Decimal | None
    received_amount: Decimal | None
    received_currency: str | None
    received_exchange_rate: Decimal | None
    fee_amount: Decimal
    fee_paid_by: str
    base_amount: Decimal | None
    eligible_amount_base: Decimal | None
    project_id: uuid.UUID | None
    employee_id: uuid.UUID | None
    salary_period_id: uuid.UUID | None
    reference_no: str | None
    description: str | None
    journal_entry_id: uuid.UUID | None
    reversal_journal_entry_id: uuid.UUID | None
    amended_from_id: uuid.UUID | None
    submitted_at: datetime | None
    submitted_by: uuid.UUID | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    reconciled_at: datetime | None
    created_at: datetime
    created_by: uuid.UUID | None
    version: int
    party_name: str | None = None
    project_name: str | None = None
    employee_name: str | None = None  # salary payments and employee-tagged expenses
    salary_period_label: str | None = None
    allocations: list[AllocationOut] = []


class PaymentPreviewLine(BaseModel):
    account_id: uuid.UUID
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    currency: str
    amount_in_currency: Decimal
    description: str | None


class PaymentPreviewOut(BaseModel):
    ok: bool
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    lines: list[PaymentPreviewLine] = []
    base_currency: str
    base_amount: Decimal | None = None
    eligible_amount_base: Decimal | None = None
    exchange_rate: Decimal | None = None  # the rate that will be used
    received_exchange_rate: Decimal | None = None
    allocations: list[AllocationOut] = []
    allocated_total: Decimal | None = None


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ReconcileIn(BaseModel):
    reconciled: bool


# ---- payment entries: helpers ----------------------------------------------------------------------


async def _ledger_accounts(session: AsyncSession, raw: str | None) -> list[uuid.UUID] | None:
    """`account_ids` filter: the chosen accounts and everything under the groups among them."""
    ids = []
    for part in (raw or "").split(","):
        if part.strip():
            try:
                ids.append(uuid.UUID(part.strip()))
            except ValueError:
                raise ValidationFailed(
                    "Invalid account id", errors=[{"field": "account_ids", "message": f"Not an id: {part.strip()}"}]
                ) from None
    return await accounting.account_subtree(session, ids) if ids else None


async def _allocations_out(
    session: AsyncSession, rows: list[Any], amounts: list[Decimal] | None = None
) -> list[AllocationOut]:
    names = await lookup.resolve(session, "employee", (r.employee_id for r in rows))
    return [
        AllocationOut(
            employee_id=r.employee_id,
            employee_name=names.get(r.employee_id),
            project_id=r.project_id,
            method=r.method,
            percent=r.percent,
            amount=amounts[i] if amounts is not None else r.amount_base,
            status=r.status,
        )
        for i, r in enumerate(rows)
    ]


async def _own_employee(session: AsyncSession, user: CurrentUser) -> Any:
    """None when the user reads every payment; otherwise their employee record, the only one whose payments
    (revenue split to them, salary paid to them, expenses tagged to or shared with them) they may see."""
    own = await employees.for_user(session, user.id)
    if own is not None and user.restricted:  # whatever role they were given
        return own
    if user.can("payments.create") or user.can("reports.financial"):
        return None
    if own is None:
        raise NotFound("Your user is not linked to an employee record")
    return own


def _for_viewer(out: EntryOut, user: CurrentUser) -> EntryOut:
    return out.model_copy(update=HIRE_HIDDEN) if user.restricted else out


async def _entry_out(
    session: AsyncSession, pe: PaymentEntry, *, refresh: bool = False, only_employee: uuid.UUID | None = None
) -> EntryOut:
    if refresh:  # after a write: return stored values (database scale), not in-memory ones
        await session.flush()
        await session.refresh(pe)
    out = EntryOut.model_validate(pe)
    parties = await lookup.resolve(session, "party", [pe.party_id])
    projects = await lookup.resolve(session, "project", [pe.project_id])
    periods = await lookup.resolve(session, "salary_period", [pe.salary_period_id])
    employee_names = await lookup.resolve(session, "employee", [pe.employee_id])
    rows = [
        r for r in await attribution.for_payment(session, pe.id) if not only_employee or r.employee_id == only_employee
    ]
    return out.model_copy(
        update={
            "party_name": parties.get(pe.party_id) if pe.party_id else None,
            "project_name": projects.get(pe.project_id) if pe.project_id else None,
            "salary_period_label": periods.get(pe.salary_period_id) if pe.salary_period_id else None,
            "employee_name": employee_names.get(pe.employee_id) if pe.employee_id else None,
            "allocations": await _allocations_out(session, rows),
            "my_share": rows[0].amount_base if only_employee and rows else None,
        }
    )


async def _entries_out(
    session: AsyncSession, entries: list[PaymentEntry], *, only_employee: uuid.UUID | None = None
) -> list[EntryOut]:
    """List pages: the same as _entry_out, with every name and split loaded in a handful of queries."""
    parties = await lookup.resolve(session, "party", (e.party_id for e in entries))
    project_names = await lookup.resolve(session, "project", (e.project_id for e in entries))
    periods = await lookup.resolve(session, "salary_period", (e.salary_period_id for e in entries))
    splits = await attribution.for_payments(session, [e.id for e in entries])
    people = await lookup.resolve(
        session,
        "employee",
        [e.employee_id for e in entries] + [a.employee_id for rows in splits.values() for a in rows],
    )
    out = []
    for e in entries:
        allocations = [
            AllocationOut(
                employee_id=a.employee_id,
                employee_name=people.get(a.employee_id),
                project_id=a.project_id,
                method=a.method,
                percent=a.percent,
                amount=a.amount_base,
                status=a.status,
            )
            for a in splits.get(e.id, [])
            if not only_employee or a.employee_id == only_employee  # not colleagues' shares
        ]
        out.append(
            EntryOut.model_validate(e).model_copy(
                update={
                    "party_name": parties.get(e.party_id) if e.party_id else None,
                    "project_name": project_names.get(e.project_id) if e.project_id else None,
                    "salary_period_label": periods.get(e.salary_period_id) if e.salary_period_id else None,
                    "employee_name": people.get(e.employee_id) if e.employee_id else None,
                    "allocations": allocations,
                    "my_share": allocations[0].amount if only_employee and allocations else None,
                }
            )
        )
    return out


async def _preview(session: AsyncSession, pe: PaymentEntry, splits: list[Any]) -> PaymentPreviewOut:
    base = await settings.base_currency(session)
    try:
        result, prepared = await service.preview(session, pe)
    except ValidationFailed as exc:
        return PaymentPreviewOut(
            ok=False, errors=exc.errors or [{"field": "", "message": exc.detail}], base_currency=base.code
        )
    out = PaymentPreviewOut(
        ok=True,
        warnings=result.warnings,
        base_currency=base.code,
        base_amount=result.base_amount,
        eligible_amount_base=result.eligible_amount_base,
        exchange_rate=result.exchange_rate,
        received_exchange_rate=result.received_exchange_rate,
        lines=[
            PaymentPreviewLine(
                account_id=p.account.id,
                account_code=p.account.code,
                account_name=p.account.name,
                debit=p.debit,
                credit=p.credit,
                currency=p.currency,
                amount_in_currency=p.amount_in_currency,
                description=p.line.description,
            )
            for p in prepared
        ],
    )
    if result.eligible_amount_base is not None:
        amounts = attribution.compute(splits, result.eligible_amount_base, base.precision) if splits else []
        out.allocations = await _allocations_out(session, splits, amounts)
        out.allocated_total = sum(amounts, Decimal(0))
        if not splits:
            out.warnings.append("Not split between employees: this revenue won't count toward anyone's salary.")
        elif out.allocated_total != result.eligible_amount_base:
            out.ok = False
            out.errors.append(
                {
                    "field": "allocations",
                    "code": "incomplete",
                    "message": f"Split covers {out.allocated_total} of {result.eligible_amount_base}",
                }
            )
    elif pe.direction == "pay" and splits:
        amounts = attribution.compute(splits, result.base_amount, base.precision)
        out.allocations = await _allocations_out(session, splits, amounts)
        out.allocated_total = sum(amounts, Decimal(0))
        try:
            service.check_expense_split(pe, result.rule)
            if out.allocated_total > result.base_amount:
                raise ValidationFailed(
                    "Split exceeds payment",
                    errors=[{"field": "allocations", "message": f"Split is more than {result.base_amount}"}],
                )
        except ValidationFailed as exc:
            out.ok = False
            out.errors.extend(exc.errors or [{"field": "allocations", "message": exc.detail}])
    return out


def _transient_splits(rows: list[SplitRow] | None, project_id: uuid.UUID | None) -> list[attribution.RevenueAllocation]:
    method = "amount" if rows and rows[0].amount is not None and rows[0].percent is None else "percent"
    return [
        attribution.RevenueAllocation(
            employee_id=r.employee_id,
            project_id=r.project_id or project_id,
            method=method,
            percent=r.percent,
            amount_base=r.amount,
            status="draft",
        )
        for r in rows or []
    ]


# ---- payment entries: endpoints --------------------------------------------------------------------


@router.get("/payment-entries", response_model=Page[EntryOut])
async def list_entries(
    params: PageParams = Depends(page_params),
    status: Literal["draft", "submitted", "cancelled"] | None = None,
    direction: Direction | None = None,
    party_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    payment_account_id: uuid.UUID | None = None,
    method_category_id: uuid.UUID | None = None,
    purpose_category_id: uuid.UUID | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    q: Annotated[str | None, Query(max_length=100)] = None,
    employee_id: uuid.UUID | None = None,
    account_ids: Annotated[
        str | None, Query(description="Comma-separated ledger accounts; a group includes its children")
    ] = None,
    format: Format = "json",
    user: CurrentUser = ReadOwnPayments,
    session: AsyncSession = Depends(get_session),
) -> Any:
    own = await _own_employee(session, user)
    if own:
        employee_id = own.id
    if user.restricted:  # Only money that has actually been paid to them.
        status, party_id, payment_account_id, account_ids = "submitted", own.party_id, None, None
    employee_party_id = (await employees.get(session, employee_id)).party_id if employee_id else None
    stmt = service.list_stmt(
        account_ids=await _ledger_accounts(session, account_ids),
        employee_id=employee_id,
        employee_party_id=employee_party_id,
        status=status,
        direction=direction,
        party_id=party_id,
        project_id=project_id,
        payment_account_id=payment_account_id,
        method_category_id=method_category_id,
        purpose_category_id=purpose_category_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
        # Searching a hidden field would let a hire guess what it says.
        search_description=not (user.restricted),
    )
    if format != "json":
        rows = list((await session.execute(stmt.limit(20000))).scalars())
        parties = await lookup.resolve(session, "party", (r.party_id for r in rows))
        projects = await lookup.resolve(session, "project", (r.project_id for r in rows))
        splits: dict[uuid.UUID, list[str]] = {}
        for r in rows:
            allocations = [
                a for a in await attribution.for_payment(session, r.id) if not own or a.employee_id == own.id
            ]
            if allocations:
                names = await lookup.resolve(session, "employee", (a.employee_id for a in allocations))
                splits[r.id] = [
                    f"{names.get(a.employee_id, '?')} {a.percent.normalize():f}%"
                    if a.percent is not None
                    else f"{names.get(a.employee_id, '?')} {a.amount_base}"
                    for a in allocations
                ]
        tagged = await lookup.resolve(session, "employee", (r.employee_id for r in rows))
        # Employee view: what each payment means for them (their share of a split one).
        mine = (
            {
                r.id: a.amount_base
                for r in rows
                for a in await attribution.for_payment(session, r.id)
                if a.employee_id == own.id
            }
            if own
            else {}
        )
        header = [
            "number",
            "posting_date",
            "status",
            "direction",
            "party",
            "project",
            "employees",
            "amount",
            "currency",
            "base_amount",
            "fee_amount",
            "fee_paid_by",
            "reference_no",
            "description",
            *(["your_share"] if own else []),
        ]
        hidden = HIRE_HIDDEN_COLUMNS if user.restricted else set()
        keep = [i for i, column in enumerate(header) if column not in hidden]
        return export_response(
            format,
            "payment-entries",
            [header[i] for i in keep],
            (
                [row[i] for i in keep]
                for row in (
                    [
                        r.number,
                        r.posting_date,
                        r.status,
                        r.direction,
                        parties.get(r.party_id, "") if r.party_id else "",
                        projects.get(r.project_id, "") if r.project_id else "",
                        "; ".join(splits.get(r.id, [])) or (tagged.get(r.employee_id, "") if r.employee_id else ""),
                        r.amount,
                        r.currency,
                        r.base_amount,
                        r.fee_amount,
                        r.fee_paid_by,
                        r.reference_no,
                        r.description,
                        *([mine.get(r.id, r.base_amount)] if own else []),
                    ]
                    for r in rows
                )
            ),
        )
    rows, total = await paginate(session, stmt, params)
    return Page(
        items=[
            _for_viewer(o, user) for o in await _entries_out(session, list(rows), only_employee=own.id if own else None)
        ],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


class EntryTotalsOut(BaseModel):
    count: int
    received: Decimal  # submitted receipts, base currency
    paid: Decimal  # submitted payments out
    transferred: Decimal  # submitted transfers between own accounts
    base_currency: str


@router.get("/payment-entries/totals", response_model=EntryTotalsOut)
async def entry_totals(
    status: Literal["draft", "submitted", "cancelled"] | None = None,
    direction: Direction | None = None,
    party_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    payment_account_id: uuid.UUID | None = None,
    method_category_id: uuid.UUID | None = None,
    purpose_category_id: uuid.UUID | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    q: Annotated[str | None, Query(max_length=100)] = None,
    employee_id: uuid.UUID | None = None,
    account_ids: Annotated[
        str | None, Query(description="Comma-separated ledger accounts; a group includes its children")
    ] = None,
    user: CurrentUser = ReadOwnPayments,
    session: AsyncSession = Depends(get_session),
) -> EntryTotalsOut:
    """Totals for the same filters as the list (what an employee or an account moved)."""
    own = await _own_employee(session, user)
    if own:
        employee_id = own.id
    if user.restricted:
        status, party_id, payment_account_id, account_ids = "submitted", own.party_id, None, None
    employee_party_id = (await employees.get(session, employee_id)).party_id if employee_id else None
    stmt = service.list_stmt(
        account_ids=await _ledger_accounts(session, account_ids),
        employee_id=employee_id,
        employee_party_id=employee_party_id,
        status=status,
        direction=direction,
        party_id=party_id,
        project_id=project_id,
        payment_account_id=payment_account_id,
        method_category_id=method_category_id,
        purpose_category_id=purpose_category_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
        # Searching a hidden field would let a hire guess what it says.
        search_description=not (user.restricted),
    )
    t = await service.totals(session, stmt, share_of=own.id if own else None)
    return EntryTotalsOut(**t, base_currency=(await settings.base_currency(session)).code)


class MyHireOut(BaseModel):
    party_id: uuid.UUID
    full_name: str


@router.get("/payment-entries/my-hires", response_model=list[MyHireOut])
async def my_hires(
    user: CurrentUser = ReadOwnPayments, session: AsyncSession = Depends(get_session)
) -> list[MyHireOut]:
    """The signed-in employee's hires, to filter their payments by: on their projects now, or paid by them before."""
    own = await employees.for_user(session, user.id)
    if own is None or user.restricted:
        return []
    hires = await employees.all_hires(session)
    current = {p.hire_employee_id for p in await projects.with_hires(session) if p.manager_employee_id == own.id}
    paid = await service.parties_paid_for(session, employee_id=own.id, party_ids=[h.party_id for h in hires])
    return [
        MyHireOut(party_id=h.party_id, full_name=h.full_name) for h in hires if h.id in current or h.party_id in paid
    ]


@router.get("/payment-entries/proposal", response_model=list[SplitRow])
async def proposal(
    project_id: uuid.UUID,
    _: CurrentUser = Depends(require("payments.create")),
    session: AsyncSession = Depends(get_session),
) -> list[SplitRow]:
    return [
        SplitRow(employee_id=s.employee_id, percent=s.percent, project_id=s.project_id)
        for s in await attribution.proposal(session, project_id)
    ]


@router.get("/payment-entries/party-summary")
async def party_summary(
    party_id: uuid.UUID, _: CurrentUser = ReadPayments, session: AsyncSession = Depends(get_session)
) -> dict[str, Decimal]:
    return await service.party_totals(session, party_id)


@router.post("/payment-entries/preview", response_model=PaymentPreviewOut)
async def preview_unsaved(
    body: EntryCreateIn,
    _: CurrentUser = Depends(require("payments.create")),
    session: AsyncSession = Depends(get_session),
) -> PaymentPreviewOut:
    pe = PaymentEntry(id=uuid.uuid4(), status="draft")
    await service.apply_fields(session, pe, body.model_dump(exclude={"allocations"}))
    rows = body.allocations
    if rows is None and pe.project_id and pe.direction == "receive":  # same pre-fill a new draft gets
        rows = [
            SplitRow(employee_id=s.employee_id, percent=s.percent, project_id=s.project_id)
            for s in await attribution.proposal(session, pe.project_id)
        ]
    splits = _transient_splits(rows, pe.project_id)
    out = await _preview(session, pe, splits)
    await session.rollback()  # nothing from a preview is ever written
    return out


@router.get("/payment-entries/{pe_id}", response_model=EntryOut)
async def get_entry(
    pe_id: uuid.UUID, user: CurrentUser = ReadOwnPayments, session: AsyncSession = Depends(get_session)
) -> EntryOut:
    pe = await service.get(session, pe_id)
    own = await _own_employee(session, user)
    if own and not await service.involves(session, pe.id, employee_id=own.id, employee_party_id=own.party_id):
        raise NotFound("Payment entry not found")
    if user.restricted and (pe.status != "submitted" or pe.party_id != own.party_id):
        raise NotFound("Payment entry not found")
    return _for_viewer(await _entry_out(session, pe, only_employee=own.id if own else None), user)


@router.get("/payment-entries/{pe_id}/preview", response_model=PaymentPreviewOut)
async def preview_saved(
    pe_id: uuid.UUID, _: CurrentUser = ReadPayments, session: AsyncSession = Depends(get_session)
) -> PaymentPreviewOut:
    pe = await service.get(session, pe_id)
    return await _preview(session, pe, await attribution.for_payment(session, pe.id))


@router.post("/payment-entries", response_model=EntryOut, status_code=201)
async def create_entry(
    body: EntryCreateIn,
    request: Request,
    user: CurrentUser = Depends(require("payments.create")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    async def action() -> EntryOut:
        splits = [r.to_service() for r in body.allocations] if body.allocations is not None else None
        pe = await service.create_draft(
            session, actor_id=user.id, data=body.model_dump(exclude={"allocations"}), splits=splits
        )
        return await _entry_out(session, pe, refresh=True)

    return await run_idempotent(request, session, user.id, body.model_dump(mode="json"), action, status_code=201)


@router.patch("/payment-entries/{pe_id}", response_model=EntryOut)
async def update_entry(
    pe_id: uuid.UUID,
    body: EntryUpdateIn,
    user: CurrentUser = Depends(require("payments.create")),
    session: AsyncSession = Depends(get_session),
) -> EntryOut:
    changes = body.model_dump(exclude_unset=True, exclude={"version", "allocations"})
    splits = [r.to_service() for r in body.allocations] if body.allocations is not None else None
    pe = await service.update_draft(
        session, actor_id=user.id, pe_id=pe_id, version=body.version, changes=changes, splits=splits
    )
    await session.commit()
    return await _entry_out(session, pe, refresh=True)


@router.delete("/payment-entries/{pe_id}", status_code=204)
async def delete_entry(
    pe_id: uuid.UUID,
    user: CurrentUser = Depends(require("payments.create")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await service.delete_draft(session, actor_id=user.id, pe_id=pe_id)
    await session.commit()
    return Response(status_code=204)


@router.post("/payment-entries/{pe_id}/submit", response_model=EntryOut)
async def submit_entry(
    pe_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require("payments.submit")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    async def action() -> EntryOut:
        return await _entry_out(session, await service.submit(session, actor_id=user.id, pe_id=pe_id), refresh=True)

    return await run_idempotent(request, session, user.id, {"submit": str(pe_id)}, action, required=True)


@router.post("/payment-entries/{pe_id}/cancel", response_model=EntryOut)
async def cancel_entry(
    pe_id: uuid.UUID,
    body: CancelIn,
    request: Request,
    user: CurrentUser = Depends(require("payments.cancel")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    async def action() -> EntryOut:
        pe = await service.cancel(session, actor_id=user.id, pe_id=pe_id, reason=body.reason)
        return await _entry_out(session, pe, refresh=True)

    return await run_idempotent(request, session, user.id, body.model_dump(mode="json"), action, required=True)


@router.post("/payment-entries/{pe_id}/amend", response_model=EntryOut, status_code=201)
async def amend_entry(
    pe_id: uuid.UUID,
    user: CurrentUser = Depends(require("payments.create")),
    session: AsyncSession = Depends(get_session),
) -> EntryOut:
    pe = await service.amend(session, actor_id=user.id, pe_id=pe_id)
    await session.commit()
    return await _entry_out(session, pe)


@router.post("/payment-entries/{pe_id}/reconcile", response_model=EntryOut)
async def reconcile_entry(
    pe_id: uuid.UUID,
    body: ReconcileIn,
    user: CurrentUser = Depends(require("payments.submit")),
    session: AsyncSession = Depends(get_session),
) -> EntryOut:
    pe = await service.set_reconciled(session, actor_id=user.id, pe_id=pe_id, reconciled=body.reconciled)
    await session.commit()
    return await _entry_out(session, pe)
