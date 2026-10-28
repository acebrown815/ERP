import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.core.numbering import next_number
from app.core.outbox import emit
from app.modules.accounting import api as accounting
from app.modules.attribution import api as attribution
from app.modules.audit import api as audit
from app.modules.categories import api as categories
from app.modules.payments import posting
from app.modules.payments.models import PaymentAccount, PaymentEntry
from app.modules.settings import api as settings

ENTRY_FIELDS = (
    "posting_date",
    "direction",
    "party_id",
    "method_category_id",
    "method_other_text",
    "purpose_category_id",
    "purpose_other_text",
    "category_id",
    "category_other_text",
    "paid_from_payment_account_id",
    "paid_to_payment_account_id",
    "counter_account_id",
    "amount",
    "exchange_rate",
    "received_amount",
    "received_exchange_rate",
    "fee_amount",
    "fee_paid_by",
    "project_id",
    "employee_id",
    "reference_no",
    "description",
)


# ---- payment accounts ------------------------------------------------------------------------------


async def get_payment_account(session: AsyncSession, pa_id: uuid.UUID) -> PaymentAccount:
    pa = await session.get(PaymentAccount, pa_id)
    if pa is None:
        raise NotFound("Payment account not found")
    return pa


async def list_payment_accounts(session: AsyncSession, *, include_inactive: bool) -> list[PaymentAccount]:
    stmt = select(PaymentAccount).order_by(func.lower(PaymentAccount.name))
    if not include_inactive:
        stmt = stmt.where(PaymentAccount.is_active.is_(True))
    return list((await session.execute(stmt)).scalars())


async def _check_ledger_account(session: AsyncSession, account_id: uuid.UUID, exclude: uuid.UUID | None) -> Any:
    try:
        account = await accounting.get_account(session, account_id)
    except NotFound:
        raise ValidationFailed("Unknown account", errors=[field_error("account_id", "Not found")]) from None
    if account.is_group or account.account_type not in accounting.MONEY_ACCOUNT_TYPES:
        raise ValidationFailed(
            "Not a money account",
            errors=[field_error("account_id", "Choose a bank, cash, crypto wallet or credit card account")],
        )
    stmt = select(PaymentAccount.id).where(PaymentAccount.account_id == account_id)
    if exclude:
        stmt = stmt.where(PaymentAccount.id != exclude)
    if (await session.execute(stmt)).first():
        raise ValidationFailed("Already used", errors=[field_error("account_id", "Another payment account uses it")])
    return account


async def _check_name(session: AsyncSession, name: str, exclude: uuid.UUID | None) -> None:
    stmt = select(PaymentAccount.id).where(func.lower(PaymentAccount.name) == name.strip().lower())
    if exclude:
        stmt = stmt.where(PaymentAccount.id != exclude)
    if (await session.execute(stmt)).first():
        raise ValidationFailed("Name in use", errors=[field_error("name", "A payment account has this name")])


async def create_payment_account(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    name: str,
    account_id: uuid.UUID,
    details: dict[str, Any] | None = None,
    notes: str | None = None,
) -> PaymentAccount:
    await _check_name(session, name, None)
    account = await _check_ledger_account(session, account_id, None)
    pa = PaymentAccount(
        name=name.strip(),
        account_id=account.id,
        kind=account.account_type,
        currency=account.currency,
        details=details or {},
        notes=notes,
        created_by=actor_id,
        updated_by=actor_id,
    )
    session.add(pa)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="payment_account.created",
        entity_type="payment_account",
        entity_id=pa.id,
        after={"name": pa.name, "account": account.code, "currency": pa.currency},
    )
    return pa


async def update_payment_account(
    session: AsyncSession, *, actor_id: uuid.UUID, pa_id: uuid.UUID, version: int, changes: dict[str, Any]
) -> PaymentAccount:
    pa = await get_payment_account(session, pa_id)
    if pa.version != version:
        raise PreconditionFailed()
    before = {"name": pa.name, "details": pa.details, "notes": pa.notes, "is_active": pa.is_active}
    if "name" in changes:
        await _check_name(session, changes["name"], pa.id)
        pa.name = changes["name"].strip()
    if changes.get("details") is not None:
        pa.details = changes["details"]
    if "notes" in changes:
        pa.notes = changes["notes"]
    if changes.get("is_active") is not None:
        pa.is_active = changes["is_active"]
    pa.version += 1
    pa.updated_by = actor_id
    await session.flush()
    b, a = audit.diff(before, {"name": pa.name, "details": pa.details, "notes": pa.notes, "is_active": pa.is_active})
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="payment_account.updated",
            entity_type="payment_account",
            entity_id=pa.id,
            before=b,
            after=a,
        )
    return pa


async def seed_payment_accounts(session: AsyncSession) -> int:
    """One payment account per money account in the default chart, if none exist yet."""
    if (await session.execute(select(func.count()).select_from(PaymentAccount))).scalar_one():
        return 0
    created = 0
    for code, name in (
        ("1110", "Company Checking"),
        ("1120", "Company Savings"),
        ("1210", "Petty Cash"),
        ("2310", "Corporate Credit Card"),
        ("1310", "Bitcoin Wallet"),
        ("1320", "USDT Wallet"),
    ):
        account = await accounting.account_by_code(session, code)
        if account is not None and account.account_type in accounting.MONEY_ACCOUNT_TYPES:
            await create_payment_account(session, actor_id=None, name=name, account_id=account.id)
            created += 1
    return created


# ---- payment entries -------------------------------------------------------------------------------


def _snapshot(pe: PaymentEntry) -> dict[str, Any]:
    return {k: getattr(pe, k) for k in (*ENTRY_FIELDS, "status", "currency")}


async def get(session: AsyncSession, pe_id: uuid.UUID, *, lock: bool = False) -> PaymentEntry:
    stmt = select(PaymentEntry).where(PaymentEntry.id == pe_id)
    if lock:
        stmt = stmt.with_for_update()
    pe = (await session.execute(stmt)).scalar_one_or_none()
    if pe is None:
        raise NotFound("Payment entry not found")
    return pe


def list_stmt(
    *,
    status: str | None,
    direction: str | None,
    party_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    payment_account_id: uuid.UUID | None,
    method_category_id: uuid.UUID | None,
    purpose_category_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    q: str | None,
) -> Select[tuple[PaymentEntry]]:
    stmt = select(PaymentEntry).order_by(PaymentEntry.posting_date.desc(), PaymentEntry.number.desc())
    for col, value in (
        (PaymentEntry.status, status),
        (PaymentEntry.direction, direction),
        (PaymentEntry.party_id, party_id),
        (PaymentEntry.project_id, project_id),
        (PaymentEntry.method_category_id, method_category_id),
        (PaymentEntry.purpose_category_id, purpose_category_id),
    ):
        if value:
            stmt = stmt.where(col == value)
    if payment_account_id:
        stmt = stmt.where(
            or_(
                PaymentEntry.paid_from_payment_account_id == payment_account_id,
                PaymentEntry.paid_to_payment_account_id == payment_account_id,
            )
        )
    if date_from:
        stmt = stmt.where(PaymentEntry.posting_date >= date_from)
    if date_to:
        stmt = stmt.where(PaymentEntry.posting_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                PaymentEntry.number.ilike(like),
                PaymentEntry.reference_no.ilike(like),
                PaymentEntry.description.ilike(like),
            )
        )
    return stmt


async def apply_fields(session: AsyncSession, pe: PaymentEntry, data: dict[str, Any]) -> None:
    for k in ENTRY_FIELDS:
        if k in data:
            setattr(pe, k, data[k])
    # The transaction currency is always the currency of our side of the payment.
    ours_id = pe.paid_to_payment_account_id if pe.direction == "receive" else pe.paid_from_payment_account_id
    if ours_id:
        pa = await session.get(PaymentAccount, ours_id)
        if pa:
            pe.currency = pa.currency
    if pe.direction == "internal_transfer" and pe.paid_to_payment_account_id:
        dst = await session.get(PaymentAccount, pe.paid_to_payment_account_id)
        pe.received_currency = dst.currency if dst else None
    else:
        pe.received_amount = pe.received_currency = pe.received_exchange_rate = None
    if not pe.currency:
        pe.currency = (await settings.base_currency(session)).code


async def _default_split(
    session: AsyncSession, pe: PaymentEntry, splits: list[attribution.SplitIn] | None
) -> list[attribution.SplitIn] | None:
    """Pre-fill a customer payment's split from its project when the caller sent none."""
    if splits is not None or not pe.project_id or not pe.purpose_category_id:
        return splits
    purpose = await categories.get(session, pe.purpose_category_id)
    if not purpose.config.get("requires_attribution"):
        return splits
    return await attribution.proposal(session, pe.project_id)


async def create_draft(
    session: AsyncSession, *, actor_id: uuid.UUID, data: dict[str, Any], splits: list[attribution.SplitIn] | None
) -> PaymentEntry:
    pe = PaymentEntry(
        number=await next_number(session, "PE", data["posting_date"]),
        status="draft",
        created_by=actor_id,
        updated_by=actor_id,
        fee_amount=Decimal(0),
        exchange_rate=Decimal(1),
    )
    await apply_fields(session, pe, data)
    session.add(pe)
    await session.flush()
    splits = await _default_split(session, pe, splits)
    if splits:
        await attribution.replace_draft(session, payment_id=pe.id, rows=splits, default_project_id=pe.project_id)
    await audit.record(
        session,
        actor_id=actor_id,
        action="payment_entry.created",
        entity_type="payment_entry",
        entity_id=pe.id,
        after={"number": pe.number, **_snapshot(pe)},
    )
    return pe


async def update_draft(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    pe_id: uuid.UUID,
    version: int,
    changes: dict[str, Any],
    splits: list[attribution.SplitIn] | None,
) -> PaymentEntry:
    pe = await get(session, pe_id, lock=True)
    if pe.status != "draft":
        raise Conflict("Only drafts can be edited. Cancel and amend a submitted payment instead.")
    if pe.version != version:
        raise PreconditionFailed()
    before = _snapshot(pe)
    await apply_fields(session, pe, changes)
    pe.version += 1
    pe.updated_by = actor_id
    await session.flush()
    if splits is not None:
        await attribution.replace_draft(session, payment_id=pe.id, rows=splits, default_project_id=pe.project_id)
    b, a = audit.diff(before, _snapshot(pe))
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="payment_entry.updated",
            entity_type="payment_entry",
            entity_id=pe.id,
            before=b,
            after=a,
        )
    return pe


async def delete_draft(session: AsyncSession, *, actor_id: uuid.UUID, pe_id: uuid.UUID) -> None:
    pe = await get(session, pe_id, lock=True)
    if pe.status != "draft":
        raise Conflict("Only drafts can be deleted")
    referenced = (await session.execute(select(PaymentEntry.id).where(PaymentEntry.amended_from_id == pe.id))).first()
    if referenced:
        raise Conflict("This draft is referenced by an amendment")
    number = pe.number
    await session.delete(pe)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="payment_entry.deleted",
        entity_type="payment_entry",
        entity_id=pe_id,
        before={"number": number},
    )


async def preview(session: AsyncSession, pe: PaymentEntry) -> tuple[posting.Posting, list[accounting.PreparedLine]]:
    result = await posting.build(session, pe)
    prepared = await accounting.prepare_lines(session, result.lines)
    if pe.party_id and pe.amount:
        window = (pe.posting_date - timedelta(days=7), pe.posting_date + timedelta(days=7))
        dup = (
            (
                await session.execute(
                    select(PaymentEntry.number).where(
                        PaymentEntry.party_id == pe.party_id,
                        PaymentEntry.amount == pe.amount,
                        PaymentEntry.status == "submitted",
                        PaymentEntry.posting_date.between(*window),
                        PaymentEntry.id != pe.id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if dup:
            result.warnings.append(f"Possible duplicate of {dup} (same party and amount within 7 days)")
    return result, prepared


async def submit(session: AsyncSession, *, actor_id: uuid.UUID, pe_id: uuid.UUID) -> PaymentEntry:
    """One transaction: validate, post to the ledger, activate the revenue split (Section 7.1)."""
    pe = await get(session, pe_id, lock=True)
    if pe.status != "draft":
        raise Conflict(f"Payment is already {pe.status}")
    result = await posting.build(session, pe)
    entry = await accounting.post_journal(
        session,
        actor_id=actor_id,
        posting_date=pe.posting_date,
        entry_type="payment",
        lines=result.lines,
        memo=pe.description,
        source_type="payment_entry",
        source_id=pe.id,
        source_number=pe.number,
    )
    pe.base_amount = result.base_amount
    pe.eligible_amount_base = result.eligible_amount_base
    if result.employee_id and not pe.employee_id:
        pe.employee_id = result.employee_id
    if pe.direction == "internal_transfer":
        if pe.received_amount is None:
            pe.received_amount = pe.amount
        if pe.received_exchange_rate is None:
            pe.received_exchange_rate = pe.exchange_rate
    if result.eligible_amount_base is not None:
        base = await settings.base_currency(session)
        await attribution.activate(
            session,
            payment_id=pe.id,
            eligible=result.eligible_amount_base,
            on=pe.posting_date,
            precision=base.precision,
        )
    pe.status = "submitted"
    pe.journal_entry_id = entry.id
    pe.submitted_at = datetime.now(UTC)
    pe.submitted_by = actor_id
    pe.version += 1
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="payment_entry.submitted",
        entity_type="payment_entry",
        entity_id=pe.id,
        after={"number": pe.number, "journal_entry": entry.number, "base_amount": pe.base_amount},
    )
    emit(session, "payment.submitted", {"payment_entry_id": str(pe.id)})
    return pe


async def cancel(session: AsyncSession, *, actor_id: uuid.UUID, pe_id: uuid.UUID, reason: str) -> PaymentEntry:
    pe = await get(session, pe_id, lock=True)
    if pe.status != "submitted":
        raise Conflict("Only submitted payments can be cancelled")
    if pe.journal_entry_id is None:
        raise Conflict("Payment has no journal entry")
    reversal = await accounting.reverse_journal(
        session, actor_id=actor_id, journal_entry_id=pe.journal_entry_id, reason=reason
    )
    await attribution.cancel(session, payment_id=pe.id)
    pe.status = "cancelled"
    pe.reversal_journal_entry_id = reversal.id
    pe.cancelled_at = datetime.now(UTC)
    pe.cancelled_by = actor_id
    pe.cancel_reason = reason
    pe.version += 1
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="payment_entry.cancelled",
        entity_type="payment_entry",
        entity_id=pe.id,
        after={"number": pe.number, "reason": reason, "reversal": reversal.number},
    )
    emit(session, "payment.cancelled", {"payment_entry_id": str(pe.id)})
    return pe


async def amend(session: AsyncSession, *, actor_id: uuid.UUID, pe_id: uuid.UUID) -> PaymentEntry:
    original = await get(session, pe_id)
    if original.status != "cancelled":
        raise Conflict("Only cancelled payments can be amended")
    existing = (
        await session.execute(select(PaymentEntry).where(PaymentEntry.amended_from_id == original.id))
    ).scalar_one_or_none()
    if existing:
        raise Conflict(f"Already amended as {existing.number}")
    data = {k: getattr(original, k) for k in ENTRY_FIELDS}
    pe = PaymentEntry(
        number=await next_number(session, "PE", original.posting_date),
        status="draft",
        amended_from_id=original.id,
        created_by=actor_id,
        updated_by=actor_id,
    )
    await apply_fields(session, pe, data)
    session.add(pe)
    await session.flush()
    await attribution.copy_as_draft(session, from_payment_id=original.id, to_payment_id=pe.id)
    await audit.record(
        session,
        actor_id=actor_id,
        action="payment_entry.amended",
        entity_type="payment_entry",
        entity_id=pe.id,
        after={"number": pe.number, "amended_from": original.number},
    )
    return pe


async def set_reconciled(
    session: AsyncSession, *, actor_id: uuid.UUID, pe_id: uuid.UUID, reconciled: bool
) -> PaymentEntry:
    pe = await get(session, pe_id, lock=True)
    if pe.status != "submitted":
        raise Conflict("Only submitted payments can be marked as checked against the bank")
    pe.reconciled_at = datetime.now(UTC) if reconciled else None
    pe.version += 1
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="payment_entry.reconciled" if reconciled else "payment_entry.unreconciled",
        entity_type="payment_entry",
        entity_id=pe.id,
    )
    return pe


async def party_totals(session: AsyncSession, party_id: uuid.UUID) -> dict[str, Decimal]:
    rows = (
        await session.execute(
            select(PaymentEntry.direction, func.sum(PaymentEntry.base_amount), func.count())
            .where(PaymentEntry.party_id == party_id, PaymentEntry.status == "submitted")
            .group_by(PaymentEntry.direction)
        )
    ).all()
    out = {"received": Decimal(0), "paid": Decimal(0), "count": Decimal(0)}
    for direction, total, count in rows:
        out["received" if direction == "receive" else "paid"] += total or Decimal(0)
        out["count"] += count
    return out
