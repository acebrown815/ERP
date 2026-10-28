"""Salary periods, statements, adjustments and balances (docs/architecture.md, Section 10).

Open periods are calculated live from the revenue split, the employee's formula and manual
adjustments, so they are always current. Closing a period freezes its statements into rows; those rows
are what a closed period shows from then on, regardless of later changes.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationFailed, field_error
from app.core.money import quantize
from app.modules.attribution import api as attribution
from app.modules.audit import api as audit
from app.modules.compensation import api as compensation
from app.modules.employees import api as employees
from app.modules.salary import cycle
from app.modules.salary.models import SalaryAdjustment, SalaryPayment, SalaryPeriod, SalaryStatement
from app.modules.settings import api as settings

ZERO = Decimal(0)
ADJUSTMENT_LABELS = {"bonus": "Bonus", "deduction": "Deduction", "correction": "Correction"}


# ---- periods ---------------------------------------------------------------------------------------


async def _lock_periods(session: AsyncSession) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('salary_periods'))"))


async def _bounds(session: AsyncSession) -> tuple[SalaryPeriod | None, SalaryPeriod | None]:
    first = (
        await session.execute(select(SalaryPeriod).order_by(SalaryPeriod.start_date).limit(1))
    ).scalar_one_or_none()
    last = (
        await session.execute(select(SalaryPeriod).order_by(SalaryPeriod.start_date.desc()).limit(1))
    ).scalar_one_or_none()
    return first, last


def _row(span: cycle.Span) -> SalaryPeriod:
    return SalaryPeriod(
        label=span.label, start_date=span.start, end_date=span.end, is_transition=span.is_transition, status="open"
    )


async def ensure_covering(session: AsyncSession, on: date) -> None:
    """Create periods so `on` falls inside one, extending the contiguous series either way."""
    first, last = await _bounds(session)
    if first and last and first.start_date <= on <= last.end_date:
        return
    await _lock_periods(session)
    first, last = await _bounds(session)
    day = (await settings.get_company(session)).salary_cycle_start_day
    if first is None or last is None:
        session.add(_row(cycle.regular(day, on)))
        await session.flush()
        return
    end, start = last.end_date, first.start_date
    while on > end:
        span = cycle.next_after(end, day)
        session.add(_row(span))
        end = span.end
    while on < start:
        span = cycle.previous_before(start, day)
        session.add(_row(span))
        start = span.start
    await session.flush()


async def period_for(session: AsyncSession, on: date) -> SalaryPeriod:
    await ensure_covering(session, on)
    return (
        await session.execute(select(SalaryPeriod).where(SalaryPeriod.start_date <= on, SalaryPeriod.end_date >= on))
    ).scalar_one()


async def get_period(session: AsyncSession, period_id: uuid.UUID, *, lock: bool = False) -> SalaryPeriod:
    stmt = select(SalaryPeriod).where(SalaryPeriod.id == period_id)
    if lock:
        stmt = stmt.with_for_update()
    p = (await session.execute(stmt)).scalar_one_or_none()
    if p is None:
        raise NotFound("Salary period not found")
    return p


async def list_periods(session: AsyncSession) -> list[SalaryPeriod]:
    """Every period up to the current one (plus later ones that already exist), newest first."""
    await ensure_covering(session, await settings.today(session))
    return list((await session.execute(select(SalaryPeriod).order_by(SalaryPeriod.start_date.desc()))).scalars())


async def closed_through(session: AsyncSession) -> date | None:
    return (
        await session.execute(select(func.max(SalaryPeriod.end_date)).where(SalaryPeriod.status == "closed"))
    ).scalar_one()


async def assert_open(session: AsyncSession, on: date, action: str) -> None:
    """Revenue dated in a closed period would change frozen statements (Section 10.2)."""
    period = await period_for(session, on)
    if period.status == "closed":
        raise Conflict(
            f"Salary period {period.label} ({period.start_date.isoformat()} – {period.end_date.isoformat()}) is "
            f"closed. An administrator must reopen it before {action}."
        )


# ---- statements ------------------------------------------------------------------------------------


@dataclass
class Line:
    """One employee in one period: frozen (closed period) or calculated live (open period)."""

    period: SalaryPeriod
    employee_id: uuid.UUID
    revenue: Decimal
    formula_id: uuid.UUID | None
    formula_name: str | None
    formula_version_id: uuid.UUID | None
    formula_version_no: int | None
    rate: Decimal
    formula_amount: Decimal
    adjustments_total: Decimal
    calculated: Decimal
    components: list[dict[str, Any]]
    frozen: bool
    paid: Decimal = ZERO

    @property
    def status(self) -> str:
        due = max(self.calculated, ZERO)
        if due == 0:
            return "nothing_due"
        if self.paid == 0:
            return "unpaid"
        return "paid" if self.paid >= due else "partially_paid"


def _components(result: compensation.Result) -> list[dict[str, Any]]:
    return [
        {
            "component": c.component,
            "label": c.label,
            "amount": str(c.amount),
            "basis": None if c.basis is None else str(c.basis),
            "rate": None if c.rate is None else str(c.rate),
        }
        for c in result.components
    ]


async def _adjustments(
    session: AsyncSession, period_id: uuid.UUID, employee_ids: list[uuid.UUID] | None
) -> dict[uuid.UUID, list[SalaryAdjustment]]:
    stmt = (
        select(SalaryAdjustment)
        .where(SalaryAdjustment.salary_period_id == period_id)
        .order_by(SalaryAdjustment.created_at)
    )
    if employee_ids is not None:
        stmt = stmt.where(SalaryAdjustment.employee_id.in_(employee_ids))
    out: dict[uuid.UUID, list[SalaryAdjustment]] = defaultdict(list)
    for a in (await session.execute(stmt)).scalars():
        out[a.employee_id].append(a)
    return out


async def _live(
    session: AsyncSession, period: SalaryPeriod, employee_ids: list[uuid.UUID] | None
) -> dict[uuid.UUID, Line]:
    start, end = period.start_date, period.end_date
    revenue = await attribution.employee_totals(session, date_from=start, date_to=end, employee_ids=employee_ids)
    formulas = await compensation.resolve(session, start=start, end=end, employee_ids=employee_ids)
    adjustments = await _adjustments(session, period.id, employee_ids)
    precision = (await settings.base_currency(session)).precision
    out = {}
    for emp in set(revenue) | set(formulas) | set(adjustments):
        rev = quantize(revenue.get(emp) or ZERO, precision)
        adj = [(f"{ADJUSTMENT_LABELS[a.kind]}: {a.reason}", a.amount) for a in adjustments.get(emp, [])]
        f = formulas.get(emp)
        if f is not None:
            result = compensation.calculate(f.definition, rev, adj)
        else:
            # No formula: revenue still shows (so a missing assignment is visible); only adjustments count.
            result = compensation.calculate(compensation.FormulaDefinition(rate_schedule={"mode": "none"}), rev, adj)
        out[emp] = Line(
            period=period,
            employee_id=emp,
            revenue=rev,
            formula_id=f.formula_id if f else None,
            formula_name=f.formula_name if f else None,
            formula_version_id=f.version_id if f else None,
            formula_version_no=f.version_no if f else None,
            rate=result.rate,
            formula_amount=result.formula_amount,
            adjustments_total=result.adjustments_total,
            calculated=result.amount,
            components=_components(result),
            frozen=False,
        )
    return out


async def _frozen(
    session: AsyncSession, period: SalaryPeriod, employee_ids: list[uuid.UUID] | None
) -> dict[uuid.UUID, Line]:
    stmt = select(SalaryStatement).where(SalaryStatement.salary_period_id == period.id)
    if employee_ids is not None:
        stmt = stmt.where(SalaryStatement.employee_id.in_(employee_ids))
    precision = (await settings.base_currency(session)).precision

    def q(x: Decimal) -> Decimal:
        return quantize(x, precision)

    return {
        s.employee_id: Line(
            period=period,
            employee_id=s.employee_id,
            revenue=q(s.attributed_revenue),
            formula_id=s.formula_id,
            formula_name=s.formula_name,
            formula_version_id=s.formula_version_id,
            formula_version_no=s.formula_version_no,
            rate=s.rate_applied.normalize(),
            formula_amount=q(s.formula_amount),
            adjustments_total=q(s.adjustments_total),
            calculated=q(s.calculated_amount),
            components=s.breakdown,
            frozen=True,
        )
        for s in (await session.execute(stmt)).scalars()
    }


async def lines_for(
    session: AsyncSession, period: SalaryPeriod, employee_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, Line]:
    if period.status == "closed":
        return await _frozen(session, period, employee_ids)
    return await _live(session, period, employee_ids)


# ---- payments and balances -------------------------------------------------------------------------


@dataclass
class Balance:
    employee_id: uuid.UUID
    calculated: Decimal = ZERO
    paid: Decimal = ZERO
    credit: Decimal = ZERO  # paid ahead, not yet used by any period
    lines: list[Line] = field(default_factory=list)  # oldest first

    @property
    def balance(self) -> Decimal:
        """Positive: the company owes the employee. Negative: paid ahead."""
        return self.calculated - self.paid


async def balances(
    session: AsyncSession, employee_ids: list[uuid.UUID] | None = None, *, until: date | None = None
) -> dict[uuid.UUID, Balance]:
    """Every started period's lines plus all salary payments, with payments matched to periods: payments
    for a chosen period go there first, everything else pays the oldest unpaid period (Section 10.3)."""
    until = until or await settings.today(session)
    await ensure_covering(session, until)
    periods = list(
        (
            await session.execute(
                select(SalaryPeriod).where(SalaryPeriod.start_date <= until).order_by(SalaryPeriod.start_date)
            )
        ).scalars()
    )
    precision = (await settings.base_currency(session)).precision
    zero = quantize(ZERO, precision)
    out: dict[uuid.UUID, Balance] = {}
    for p in periods:
        for emp, line in (await lines_for(session, p, employee_ids)).items():
            b = out.setdefault(emp, Balance(emp, zero, zero, zero))
            line.paid = zero
            b.lines.append(line)
            b.calculated += line.calculated

    stmt = select(SalaryPayment).order_by(SalaryPayment.paid_on, SalaryPayment.created_at)
    if employee_ids is not None:
        stmt = stmt.where(SalaryPayment.employee_id.in_(employee_ids))
    payments: dict[uuid.UUID, list[SalaryPayment]] = defaultdict(list)
    for pay in (await session.execute(stmt)).scalars():
        payments[pay.employee_id].append(pay)
        out.setdefault(pay.employee_id, Balance(pay.employee_id, zero, zero, zero))

    for emp, b in out.items():
        by_period = {line.period.id: line for line in b.lines}

        def take(line: Line, available: Decimal) -> Decimal:
            used = min(max(max(line.calculated, ZERO) - line.paid, ZERO), available)
            line.paid += used
            return available - used

        pool = zero
        for pay in payments.get(emp, []):
            amount = quantize(pay.amount, precision)
            b.paid += amount
            target = by_period.get(pay.salary_period_id) if pay.salary_period_id else None
            pool += take(target, amount) if target else amount
        for line in b.lines:
            if pool <= 0:
                break
            pool = take(line, pool)
        b.credit = pool
    return out


async def record_payment(
    session: AsyncSession,
    *,
    payment_entry_id: uuid.UUID,
    employee_id: uuid.UUID,
    amount: Decimal,
    paid_on: date,
    salary_period_id: uuid.UUID | None,
) -> None:
    """Called by payments when a salary Payment Entry is submitted."""
    if salary_period_id is not None:
        period = await get_period(session, salary_period_id)
        if period.start_date > max(paid_on, await settings.today(session)):
            raise ValidationFailed(
                "Period not started",
                errors=[field_error("salary_period_id", f"{period.label} hasn't started yet")],
            )
    session.add(
        SalaryPayment(
            payment_entry_id=payment_entry_id,
            employee_id=employee_id,
            amount=amount,
            paid_on=paid_on,
            salary_period_id=salary_period_id,
        )
    )
    await session.flush()


async def remove_payment(session: AsyncSession, *, payment_entry_id: uuid.UUID) -> None:
    """Called by payments when a salary Payment Entry is cancelled."""
    await session.execute(delete(SalaryPayment).where(SalaryPayment.payment_entry_id == payment_entry_id))


async def payments_for(session: AsyncSession, employee_id: uuid.UUID) -> list[SalaryPayment]:
    return list(
        (
            await session.execute(
                select(SalaryPayment)
                .where(SalaryPayment.employee_id == employee_id)
                .order_by(SalaryPayment.paid_on.desc(), SalaryPayment.created_at.desc())
            )
        ).scalars()
    )


# ---- adjustments -----------------------------------------------------------------------------------


async def _require_open(period: SalaryPeriod) -> None:
    if period.status == "closed":
        raise Conflict(f"Salary period {period.label} is closed")


async def list_adjustments(
    session: AsyncSession, period_id: uuid.UUID, employee_id: uuid.UUID | None = None
) -> list[SalaryAdjustment]:
    adj = await _adjustments(session, period_id, [employee_id] if employee_id else None)
    return sorted((a for rows in adj.values() for a in rows), key=lambda a: a.created_at)


async def add_adjustment(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    period_id: uuid.UUID,
    employee_id: uuid.UUID,
    kind: str,
    amount: Decimal,
    reason: str,
) -> SalaryAdjustment:
    """Bonus and deduction take a positive amount (a deduction is stored negative); a correction is signed."""
    period = await get_period(session, period_id, lock=True)
    await _require_open(period)
    await employees.get(session, employee_id)
    if amount == 0 or (kind != "correction" and amount < 0):
        raise ValidationFailed(
            "Invalid amount",
            errors=[field_error("amount", "Enter a positive amount" if kind != "correction" else "Can't be zero")],
        )
    if not reason.strip():
        raise ValidationFailed("Reason required", errors=[field_error("reason", "Say why", "required")])
    signed = -amount if kind == "deduction" else amount
    adj = SalaryAdjustment(
        salary_period_id=period.id,
        employee_id=employee_id,
        kind=kind,
        amount=signed,
        reason=reason.strip(),
        created_by=actor_id,
    )
    session.add(adj)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="salary_adjustment.created",
        entity_type="employee",
        entity_id=employee_id,
        after={"period": period.label, "kind": kind, "amount": signed, "reason": adj.reason},
    )
    return adj


async def delete_adjustment(session: AsyncSession, *, actor_id: uuid.UUID, adjustment_id: uuid.UUID) -> None:
    adj = await session.get(SalaryAdjustment, adjustment_id)
    if adj is None:
        raise NotFound("Adjustment not found")
    period = await get_period(session, adj.salary_period_id, lock=True)
    await _require_open(period)
    await session.delete(adj)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="salary_adjustment.deleted",
        entity_type="employee",
        entity_id=adj.employee_id,
        before={"period": period.label, "kind": adj.kind, "amount": adj.amount, "reason": adj.reason},
    )


# ---- close / reopen --------------------------------------------------------------------------------


def _totals(lines: list[Line]) -> dict[str, Any]:
    return {
        "employees": len(lines),
        "revenue": sum((x.revenue for x in lines), ZERO),
        "calculated": sum((x.calculated for x in lines), ZERO),
    }


async def close_period(session: AsyncSession, *, actor_id: uuid.UUID, period_id: uuid.UUID) -> SalaryPeriod:
    period = await get_period(session, period_id, lock=True)
    if period.status == "closed":
        raise Conflict(f"{period.label} is already closed")
    if period.end_date >= await settings.today(session):
        raise ValidationFailed(
            "Period not over",
            errors=[field_error("status", f"{period.label} can be closed after {period.end_date.isoformat()}")],
        )
    earlier_open = (
        await session.execute(
            select(SalaryPeriod.label)
            .where(SalaryPeriod.status == "open", SalaryPeriod.end_date < period.start_date)
            .order_by(SalaryPeriod.start_date)
            .limit(1)
        )
    ).scalar_one_or_none()
    if earlier_open:
        raise Conflict(f"Close {earlier_open} first; periods close in order")
    lines = list((await _live(session, period, None)).values())
    session.add_all(
        SalaryStatement(
            salary_period_id=period.id,
            employee_id=x.employee_id,
            formula_id=x.formula_id,
            formula_version_id=x.formula_version_id,
            formula_name=x.formula_name,
            formula_version_no=x.formula_version_no,
            attributed_revenue=x.revenue,
            rate_applied=x.rate,
            formula_amount=x.formula_amount,
            adjustments_total=x.adjustments_total,
            calculated_amount=x.calculated,
            breakdown=x.components,
        )
        for x in lines
    )
    await compensation.lock_versions(session, [x.formula_version_id for x in lines if x.formula_version_id])
    period.status = "closed"
    period.closed_at = datetime.now(UTC)
    period.closed_by = actor_id
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="salary_period.closed",
        entity_type="salary_period",
        entity_id=period.id,
        after={"label": period.label, **_totals(lines)},
    )
    return period


async def reopen_period(
    session: AsyncSession, *, actor_id: uuid.UUID, period_id: uuid.UUID, reason: str
) -> SalaryPeriod:
    period = await get_period(session, period_id, lock=True)
    if period.status != "closed":
        raise Conflict(f"{period.label} is not closed")
    if not reason.strip():
        raise ValidationFailed("Reason required", errors=[field_error("reason", "Say why", "required")])
    later_closed = (
        await session.execute(
            select(SalaryPeriod.label)
            .where(SalaryPeriod.status == "closed", SalaryPeriod.start_date > period.end_date)
            .order_by(SalaryPeriod.start_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if later_closed:
        raise Conflict(f"Reopen {later_closed} first; periods reopen newest first")
    frozen = list((await _frozen(session, period, None)).values())
    await session.execute(delete(SalaryStatement).where(SalaryStatement.salary_period_id == period.id))
    period.status = "open"
    period.reopened_at = datetime.now(UTC)
    period.reopened_by = actor_id
    period.reopen_reason = reason.strip()
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="salary_period.reopened",
        entity_type="salary_period",
        entity_id=period.id,
        before={
            "label": period.label,
            **_totals(frozen),
            "statements": {str(x.employee_id): str(x.calculated) for x in frozen},
        },
        after={"reason": period.reopen_reason},
    )
    return period


# ---- cycle setting ---------------------------------------------------------------------------------


@dataclass
class CyclePlan:
    current_day: int
    new_day: int
    fresh: bool  # nothing depends on existing periods yet: they are all regenerated
    kept: SalaryPeriod | None  # the current period, kept as it is
    upcoming: list[cycle.Span]
    blockers: list[str]


async def plan_cycle(session: AsyncSession, day: int, *, count: int = 4) -> CyclePlan:
    """What changing the start day would do (Section 10.1): periods that have started keep their dates;
    later ones are regenerated, starting with a shorter transition period if needed."""
    if not 1 <= day <= 28:
        raise ValidationFailed("Invalid day", errors=[field_error("salary_cycle_start_day", "Choose 1 to 28")])
    company = await settings.get_company(session)
    today = await settings.today(session)

    async def exists(model: Any, *where: Any) -> bool:
        return (await session.execute(select(model.id).where(*where).limit(1))).first() is not None

    fresh = not (
        await exists(SalaryPeriod, SalaryPeriod.status == "closed")
        or await exists(SalaryAdjustment)
        or await exists(SalaryPayment)
    )
    if fresh:
        first = cycle.regular(day, today)
        return CyclePlan(
            company.salary_cycle_start_day, day, True, None, [first, *cycle.upcoming(first.end, day, count - 1)], []
        )
    kept = await period_for(session, today)
    future = select(SalaryPeriod.id).where(SalaryPeriod.start_date > today)
    blockers = []
    if await exists(SalaryAdjustment, SalaryAdjustment.salary_period_id.in_(future)):
        blockers.append("Adjustments exist on periods that haven't started; delete them first.")
    if await exists(SalaryPayment, SalaryPayment.salary_period_id.in_(future)):
        blockers.append("Salary payments are assigned to periods that haven't started.")
    return CyclePlan(
        company.salary_cycle_start_day, day, False, kept, cycle.upcoming(kept.end_date, day, count), blockers
    )


async def set_cycle(session: AsyncSession, *, actor_id: uuid.UUID, day: int) -> CyclePlan:
    await _lock_periods(session)
    plan = await plan_cycle(session, day)
    if plan.blockers:
        raise Conflict(" ".join(plan.blockers))
    if plan.current_day == day:
        return plan
    today = await settings.today(session)
    if plan.fresh:
        await session.execute(delete(SalaryPeriod))
    else:
        await session.execute(delete(SalaryPeriod).where(SalaryPeriod.start_date > today))
    await settings.set_salary_cycle_start_day(session, actor_id=actor_id, day=day)
    await ensure_covering(session, today)
    return plan


# ---- reporting helpers -----------------------------------------------------------------------------


async def periods_between(session: AsyncSession, first_id: uuid.UUID, last_id: uuid.UUID) -> list[SalaryPeriod]:
    a, b = await get_period(session, first_id), await get_period(session, last_id)
    lo, hi = min(a.start_date, b.start_date), max(a.start_date, b.start_date)
    return list(
        (
            await session.execute(
                select(SalaryPeriod).where(SalaryPeriod.start_date.between(lo, hi)).order_by(SalaryPeriod.start_date)
            )
        ).scalars()
    )


async def employee_names(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return await employees.names(session, ids)
