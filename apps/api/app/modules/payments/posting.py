"""Posting rules: Payment Entry -> balanced journal lines (docs/architecture.md, Section 7.3).

Every check that decides whether a payment may be submitted lives here, so the preview shown to the
user and the actual submit always agree.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed, field_error
from app.core.money import allocate, quantize
from app.modules.accounting import api as accounting
from app.modules.categories import api as categories
from app.modules.employees import api as employees
from app.modules.parties import api as parties
from app.modules.payments.models import PaymentAccount, PaymentEntry
from app.modules.projects import api as projects
from app.modules.salary import api as salary
from app.modules.settings import api as settings

ZERO = Decimal(0)

# Which accounts the counter line may use, per direction (money accounts go through transfers instead).
COUNTER_ROOTS = {
    "receive": ("income", "equity", "liability", "asset"),
    "pay": ("expense", "equity", "liability", "asset"),
}
RULE_COUNTER_ROOTS = {"R1": ("income",), "R2": ("income",), "P1": ("expense", "asset")}
FIXED_COUNTER = {"R3": "owner_capital", "P2": "salary_expense", "P3": "owner_drawings", "P4": "hire_fees"}
RULE_PARTY_KINDS = {"R1": ("customer", "other"), "P1": ("supplier", "other"), "P2": ("employee",), "P4": ("employee",)}
REQUIRED_PARTY = {"R1": "the customer", "P2": "the employee", "P4": "the project's hire"}


@dataclass
class Posting:
    rule: str | None
    lines: list[accounting.LineIn]
    base_amount: Decimal
    eligible_amount_base: Decimal | None  # set when the purpose requires an employee split
    counter_account_id: uuid.UUID | None
    employee_id: uuid.UUID | None
    exchange_rate: Decimal = Decimal(1)  # as used: typed on the entry or the saved rate
    received_exchange_rate: Decimal | None = None  # internal transfers
    warnings: list[str] = field(default_factory=list)


class _Errors:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, f: str, message: str, code: str = "invalid") -> None:
        self.items.append(field_error(f, message, code))

    def raise_if_any(self) -> None:
        if self.items:
            raise ValidationFailed("The payment can't be submitted yet", errors=self.items)


async def _payment_account(
    session: AsyncSession, pid: uuid.UUID | None, f: str, errors: _Errors
) -> PaymentAccount | None:
    if pid is None:
        return None
    pa = await session.get(PaymentAccount, pid)
    if pa is None or not pa.is_active:
        errors.add(f, "Choose an active payment account")
        return None
    return pa


async def _rate(
    session: AsyncSession,
    currency: str,
    given: Decimal | None,
    on: date,
    f: str,
    errors: _Errors,
    base_code: str,
    warnings: list[str],
) -> Decimal:
    """The rate typed on the entry, else the saved rate for the date (Settings → Currencies & Rates)."""
    if currency == base_code:
        return Decimal(1)
    if given is not None:
        if given <= 0:
            errors.add(f, "The exchange rate must be greater than zero")
            return Decimal(1)
        return given
    try:
        rate, rate_date, _ = await settings.lookup_rate(session, currency, base_code, on)
    except NotFound:
        errors.add(
            f,
            f"No saved {currency}→{base_code} rate on or before {on.isoformat()}. "
            "Enter the rate here or add one under Settings → Currencies & Rates.",
            "required",
        )
        return Decimal(1)
    since = f" from {rate_date.isoformat()}" if rate_date else ""
    warnings.append(f"Using the saved {currency}→{base_code} rate {rate.normalize():f}{since}")
    return rate


async def _choice(session: AsyncSession, errors: _Errors, **kwargs: Any) -> Any:
    try:
        return await categories.validate_choice(session, **kwargs)
    except ValidationFailed as exc:
        errors.items.extend(exc.errors)
        return None


async def build(session: AsyncSession, pe: PaymentEntry) -> Posting:
    """Validate a payment and compute its journal lines. Raises ValidationFailed with every problem found."""
    errors = _Errors()
    base = await settings.base_currency(session)
    bp = base.precision
    q = lambda v: quantize(v, bp)  # noqa: E731

    method = await _choice(
        session,
        errors,
        group_key="payment_method",
        category_id=pe.method_category_id,
        other_text=pe.method_other_text,
        field="method_category_id",
        other_field="method_other_text",
    )
    purpose = await _choice(
        session,
        errors,
        group_key="payment_purpose",
        category_id=pe.purpose_category_id,
        other_text=pe.purpose_other_text,
        field="purpose_category_id",
        other_field="purpose_other_text",
    )
    category = None
    if pe.category_id:
        if pe.direction == "internal_transfer":
            errors.add("category_id", "Transfers have no income or expense category")
        else:
            group = "income_category" if pe.direction == "receive" else "expense_category"
            category = await _choice(
                session,
                errors,
                group_key=group,
                category_id=pe.category_id,
                other_text=pe.category_other_text,
                field="category_id",
                other_field="category_other_text",
            )
            # Fields this category makes mandatory (Settings → Custom Categories).
            for f in (category.config.get("required_fields") or []) if category else []:
                if not str(getattr(pe, f, "") or "").strip():
                    errors.add(f, f"Required for “{category.name}”", "required")

    config = dict(purpose.config) if purpose else {}
    rule: str | None = config.get("posting_rule")
    if purpose and config.get("direction") and config["direction"] != pe.direction:
        errors.add("purpose_category_id", f"“{purpose.name}” is used with direction {config['direction']}")
    if pe.direction == "internal_transfer" and purpose and rule not in (None, "T1"):
        errors.add("purpose_category_id", "Use the Internal Transfer purpose for transfers")
    if pe.direction != "internal_transfer" and rule == "T1":
        errors.add("purpose_category_id", "Internal Transfer purpose needs the Internal transfer direction")
    requires_split = bool(config.get("requires_attribution"))

    # Payment accounts ------------------------------------------------------------------------------
    src = await _payment_account(session, pe.paid_from_payment_account_id, "paid_from_payment_account_id", errors)
    dst = await _payment_account(session, pe.paid_to_payment_account_id, "paid_to_payment_account_id", errors)
    if pe.direction == "receive":
        if pe.paid_to_payment_account_id is None:
            errors.add("paid_to_payment_account_id", "Choose where the money arrived", "required")
        if pe.paid_from_payment_account_id is not None:
            errors.add("paid_from_payment_account_id", "Leave empty for a receipt")
    elif pe.direction == "pay":
        if pe.paid_from_payment_account_id is None:
            errors.add("paid_from_payment_account_id", "Choose where the money left from", "required")
        if pe.paid_to_payment_account_id is not None:
            errors.add("paid_to_payment_account_id", "Leave empty for a payment")
    else:
        if src is None and pe.paid_from_payment_account_id is None:
            errors.add("paid_from_payment_account_id", "Choose the source account", "required")
        if dst is None and pe.paid_to_payment_account_id is None:
            errors.add("paid_to_payment_account_id", "Choose the destination account", "required")
        if src and dst and src.id == dst.id:
            errors.add("paid_to_payment_account_id", "Source and destination must differ")

    ours = dst if pe.direction == "receive" else src
    if ours and method:
        allowed = method.config.get("allowed_payment_account_kinds")
        if allowed and ours.kind not in allowed:
            errors.add("method_category_id", f"“{method.name}” can't be used with a {ours.kind.replace('_', ' ')}")
        if method.config.get("requires_reference_no") and not (pe.reference_no or "").strip():
            errors.add("reference_no", f"“{method.name}” needs a reference number", "required")
    if ours and pe.currency != ours.currency:
        errors.add("currency", f"{ours.name} is in {ours.currency}")

    # Amounts ---------------------------------------------------------------------------------------
    tx_precision = (await settings.get_currency(session, pe.currency)).precision if pe.currency else bp
    if pe.amount is None or pe.amount <= 0:
        errors.add("amount", "Enter an amount greater than zero", "required")
    elif quantize(pe.amount, tx_precision) != pe.amount:
        errors.add("amount", f"{pe.currency} allows {tx_precision} decimal places")
    fee = pe.fee_amount or ZERO
    if fee < 0 or quantize(fee, tx_precision) != fee:
        errors.add("fee_amount", f"Enter a non-negative fee with at most {tx_precision} decimals")
    company_fee = fee if pe.fee_paid_by == "company" else ZERO
    if pe.direction == "receive" and pe.amount and company_fee >= pe.amount:
        errors.add("fee_amount", "The fee must be smaller than the amount")
    warnings: list[str] = []
    rate = await _rate(
        session, pe.currency, pe.exchange_rate, pe.posting_date, "exchange_rate", errors, base.code, warnings
    )

    # Party, project, employee ----------------------------------------------------------------------
    party = None
    if pe.party_id:
        try:
            party = await parties.get(session, pe.party_id)
        except NotFound:
            errors.add("party_id", "Unknown party")
    if pe.direction == "internal_transfer" and pe.party_id:
        errors.add("party_id", "Transfers between our own accounts have no party")
    kinds = RULE_PARTY_KINDS.get(rule or "")
    if kinds and rule in REQUIRED_PARTY and party is None and "party_id" not in {e["field"] for e in errors.items}:
        errors.add("party_id", f"Choose {REQUIRED_PARTY[rule]}", "required")
    if party and kinds and party.kind not in kinds:
        errors.add("party_id", f"Must be a {' or '.join(kinds)}")
    if party and not party.is_active:
        errors.add("party_id", f"{party.name} is inactive")

    employee_id = pe.employee_id
    if rule == "P2" and party:
        employee = await employees.by_party(session, party.id)
        employee_id = employee.id if employee else None
        if employee and employee.is_hired_manager:
            errors.add("party_id", "Hired managers get no salary")
    elif employee_id and rule != "P4":
        try:
            tagged = await employees.get(session, employee_id)
        except NotFound:
            errors.add("employee_id", "Unknown employee")
        else:
            if tagged.is_hired_manager:
                errors.add("employee_id", "An expense can't be charged to a hired manager")

    project = None
    if pe.project_id:
        try:
            project = await projects.get(session, pe.project_id)
        except NotFound:
            errors.add("project_id", "Unknown project")
    if rule != "P4" and project and party and project.customer_party_id and project.customer_party_id != party.id:
        warnings.append(f"{project.name} belongs to a different customer")
    if rule == "P4":
        employee_id = await _charged_for_hire(session, pe, party, project, rate, bp, errors, warnings)

    # Counter account -------------------------------------------------------------------------------
    counter = None
    if pe.direction != "internal_transfer":
        counter = await _resolve_counter(session, pe, rule, category, project, errors)

    errors.raise_if_any()
    assert pe.amount is not None

    # Lines -----------------------------------------------------------------------------------------
    fee_account = await accounting.account_by_system_key(session, "bank_fees") if company_fee else None
    tags = {"party_id": pe.party_id, "project_id": pe.project_id, "employee_id": employee_id}
    lines: list[accounting.LineIn] = []
    eligible: Decimal | None = None
    dst_rate: Decimal | None = None

    if pe.direction == "receive":
        assert dst and counter
        net = pe.amount - company_fee
        bank_base, fee_base = q(net * rate), q(company_fee * rate)
        total = bank_base + fee_base
        lines.append(
            accounting.LineIn(
                account_id=dst.account_id,
                debit=bank_base,
                amount_in_currency=net,
                exchange_rate=rate,
                description=pe.description,
                **tags,
            )
        )
        if fee_base:
            lines.append(
                accounting.LineIn(
                    account_id=fee_account.id,
                    debit=fee_base,  # type: ignore[union-attr]
                    description="Payment processing fee",
                    **tags,
                )
            )
        lines.append(
            accounting.LineIn(
                account_id=counter.id, credit=total, category_id=pe.category_id, description=pe.description, **tags
            )
        )
        base_amount = total
        if requires_split:
            basis = await settings.policy(session, "eligible_revenue_basis")
            eligible = bank_base if basis == "net_of_company_fees" else total
    elif pe.direction == "pay":
        assert src and counter
        counter_base, fee_base = q(pe.amount * rate), q(company_fee * rate)
        weights = (
            await salary.project_weights(
                session, employee_id=employee_id, salary_period_id=pe.salary_period_id, on=pe.posting_date
            )
            if rule == "P2" and employee_id and not pe.project_id
            else []
        )
        if weights:
            # Salary cost per project (Section 10.4): one expense line per project the employee earned on.
            for (project_id, _), part in zip(weights, allocate(counter_base, [w for _, w in weights], bp), strict=True):
                if part:
                    lines.append(
                        accounting.LineIn(
                            account_id=counter.id,
                            debit=part,
                            category_id=pe.category_id,
                            description=pe.description,
                            **{**tags, "project_id": project_id},
                        )
                    )
        else:
            lines.append(
                accounting.LineIn(
                    account_id=counter.id,
                    debit=counter_base,
                    category_id=pe.category_id,
                    description=pe.description,
                    **tags,
                )
            )
        if fee_base:
            lines.append(
                accounting.LineIn(
                    account_id=fee_account.id,
                    debit=fee_base,  # type: ignore[union-attr]
                    description="Payment processing fee",
                    **tags,
                )
            )
        out_units = pe.amount + company_fee
        src_base = await _outflow_base(session, src, out_units, rate, pe, base.code, bp)
        lines.append(
            accounting.LineIn(
                account_id=src.account_id,
                credit=src_base,
                amount_in_currency=-out_units,
                exchange_rate=rate,
                description=pe.description,
                **tags,
            )
        )
        await _fx_line(session, lines, src_base - counter_base - fee_base)
        base_amount = counter_base
    else:
        assert src and dst
        lines, base_amount, dst_rate = await _transfer_lines(
            session, pe, src, dst, rate, company_fee, fee_account, base, errors, warnings
        )
        errors.raise_if_any()

    return Posting(
        rule=rule,
        lines=lines,
        base_amount=base_amount,
        eligible_amount_base=eligible,
        counter_account_id=counter.id if counter else None,
        employee_id=employee_id,
        exchange_rate=rate,
        received_exchange_rate=dst_rate,
        warnings=warnings,
    )


async def _charged_for_hire(
    session: AsyncSession,
    pe: PaymentEntry,
    party: Any,
    project: Any,
    rate: Decimal,
    precision: int,
    errors: _Errors,
    warnings: list[str],
) -> uuid.UUID | None:
    """A hire is paid on a project, and the amount comes off that project's manager's revenue. The manager
    comes from the project, never from the form, so nobody else can be charged."""
    if project is None:
        if pe.project_id is None:
            errors.add("project_id", "Choose the project this payment is for", "required")
        return None
    hire = await employees.by_party(session, party.id) if party else None
    if party and (hire is None or hire.id != project.hire_employee_id):
        errors.add("party_id", "Must be this project's hire")
        return None
    if project.manager_employee_id is None:
        errors.add("project_id", "This project has no manager to charge", "required")
        return None
    manager = await employees.get(session, project.manager_employee_id)
    if manager.status == "terminated":
        warnings.append(f"{manager.full_name} has left, but will still be charged")
    if pe.amount:
        net = await salary.net_revenue(session, manager.id, pe.posting_date)
        if quantize(pe.amount * rate, precision) > net:
            warnings.append(
                f"This is more than {manager.full_name}'s net revenue for the salary period ({net}). "
                "The excess lowers their revenue to zero and no further, so the company absorbs it."
            )
    return manager.id


async def _resolve_counter(
    session: AsyncSession, pe: PaymentEntry, rule: str | None, category: Any, project: Any, errors: _Errors
) -> Any:
    """Explicit choice > category default > project type default > rule default (Section 7.2, step 2)."""
    if rule in FIXED_COUNTER:
        return await accounting.account_by_system_key(session, FIXED_COUNTER[rule])
    account_id = pe.counter_account_id
    if account_id is None and category is not None:
        account_id = _uuid(category.config.get("default_account_id"))
    if account_id is None and rule == "R1" and project is not None:
        ptype = await categories.get(session, project.project_type_category_id)
        account_id = _uuid(ptype.config.get("default_income_account_id"))
    if account_id is None and rule in ("R1", "R2"):
        key = "default_income" if rule == "R1" else "other_income"
        account_id = (await accounting.account_by_system_key(session, key)).id
    if account_id is None:
        target = "income" if pe.direction == "receive" else "expense"
        errors.add("counter_account_id", f"Choose the {target} account (or a category that has one)", "required")
        return None
    try:
        account = await accounting.get_account(session, account_id)
    except NotFound:
        errors.add("counter_account_id", "Unknown account")
        return None
    roots = RULE_COUNTER_ROOTS.get(rule or "", COUNTER_ROOTS[pe.direction])
    if account.is_group or not account.is_active:
        errors.add("counter_account_id", f"{account.code} {account.name} is a group or inactive")
    elif account.root_type not in roots:
        errors.add("counter_account_id", f"Must be a {' or '.join(roots)} account")
    elif account.account_type in accounting.MONEY_ACCOUNT_TYPES:
        errors.add("counter_account_id", "Use an internal transfer to move money between our own accounts")
    return account


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


async def _transfer_lines(
    session: AsyncSession,
    pe: PaymentEntry,
    src: PaymentAccount,
    dst: PaymentAccount,
    rate: Decimal,
    company_fee: Decimal,
    fee_account: Any,
    base: Any,
    errors: _Errors,
    warnings: list[str],
) -> tuple[list[accounting.LineIn], Decimal, Decimal | None]:
    q = lambda v: quantize(v, base.precision)  # noqa: E731
    assert pe.amount is not None
    same_currency = src.currency == dst.currency
    received = pe.received_amount if pe.received_amount is not None else (pe.amount if same_currency else None)
    if received is None or received <= 0:
        errors.add("received_amount", f"Enter how much {dst.currency} arrived", "required")
        return [], ZERO, None
    dst_precision = (await settings.get_currency(session, dst.currency)).precision
    if quantize(received, dst_precision) != received:
        errors.add("received_amount", f"{dst.currency} allows {dst_precision} decimal places")
        return [], ZERO, None
    if same_currency:
        dst_rate = rate
    else:
        dst_rate = await _rate(
            session,
            dst.currency,
            pe.received_exchange_rate,
            pe.posting_date,
            "received_exchange_rate",
            errors,
            base.code,
            warnings,
        )

    out_units = pe.amount + company_fee
    src_base = await _outflow_base(session, src, out_units, rate, pe, base.code, base.precision)
    dst_base, fee_base = q(received * dst_rate), q(company_fee * rate)
    lines = [
        accounting.LineIn(
            account_id=dst.account_id,
            debit=dst_base,
            amount_in_currency=received,
            exchange_rate=dst_rate,
            description=pe.description,
        ),
        accounting.LineIn(
            account_id=src.account_id,
            credit=src_base,
            amount_in_currency=-out_units,
            exchange_rate=rate,
            description=pe.description,
        ),
    ]
    if fee_base:
        lines.insert(1, accounting.LineIn(account_id=fee_account.id, debit=fee_base, description="Transfer fee"))
    await _fx_line(session, lines, src_base - dst_base - fee_base)
    return lines, q(pe.amount * rate), dst_rate


async def _outflow_base(
    session: AsyncSession,
    src: PaymentAccount,
    units: Decimal,
    rate: Decimal,
    pe: PaymentEntry,
    base_code: str,
    precision: int,
) -> Decimal:
    """Base value of money leaving `src`: carrying (average) cost for foreign/crypto accounts, so the account
    empties to zero value together with its units; the gap to today's value becomes realized FX gain/loss."""
    if src.currency == base_code:
        return quantize(units * rate, precision)
    carry = await accounting.carrying_rate(session, src.account_id, pe.posting_date)
    return quantize(units * (carry if carry is not None else rate), precision)


async def _fx_line(session: AsyncSession, lines: list[accounting.LineIn], diff: Decimal) -> None:
    """Positive diff: we gave up more book value than we got (loss, debit). Negative: gain (credit)."""
    if not diff:
        return
    fx = await accounting.account_by_system_key(session, "fx_gain_loss")
    side = {"debit": diff} if diff > 0 else {"credit": -diff}
    lines.append(accounting.LineIn(account_id=fx.id, description="Realized FX / crypto gain-loss", **side))
