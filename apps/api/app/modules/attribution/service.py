import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed, field_error
from app.core.money import allocate, quantize
from app.core.outbox import emit
from app.modules.attribution.models import RevenueAllocation
from app.modules.employees import api as employees
from app.modules.projects import api as projects

HUNDRED = Decimal(100)


@dataclass
class SplitIn:
    employee_id: uuid.UUID
    percent: Decimal | None = None
    amount: Decimal | None = None
    project_id: uuid.UUID | None = None


async def for_payment(session: AsyncSession, payment_id: uuid.UUID) -> list[RevenueAllocation]:
    return list(
        (
            await session.execute(
                select(RevenueAllocation)
                .where(RevenueAllocation.payment_entry_id == payment_id)
                .order_by(RevenueAllocation.created_at, RevenueAllocation.id)
            )
        ).scalars()
    )


def _method(rows: list[SplitIn]) -> str:
    kinds = {"percent" if r.percent is not None else "amount" for r in rows}
    if len(kinds) > 1 or any((r.percent is None) == (r.amount is None) for r in rows):
        raise ValidationFailed(
            "Use either percentages or amounts",
            errors=[field_error("allocations", "Every row needs a percentage, or every row an amount", "mixed")],
        )
    return kinds.pop()


async def replace_draft(
    session: AsyncSession, *, payment_id: uuid.UUID, rows: list[SplitIn], default_project_id: uuid.UUID | None
) -> list[RevenueAllocation]:
    """Replace a draft payment's split. Totals are checked against the eligible amount on submit."""
    errors = []
    ids = [r.employee_id for r in rows]
    if len(ids) != len(set(ids)):
        errors.append(field_error("allocations", "Each employee can appear only once", "duplicate"))
    for i, r in enumerate(rows):
        try:
            await employees.get(session, r.employee_id)
        except NotFound:
            errors.append(field_error(f"allocations.{i}.employee_id", "Unknown employee"))
        if r.project_id:
            try:
                await projects.get(session, r.project_id)
            except NotFound:
                errors.append(field_error(f"allocations.{i}.project_id", "Unknown project"))
        if r.percent is not None and not (0 < r.percent <= HUNDRED):
            errors.append(field_error(f"allocations.{i}.percent", "Between 0 and 100"))
        if r.amount is not None and r.amount <= 0:
            errors.append(field_error(f"allocations.{i}.amount", "Must be positive"))
    if errors:
        raise ValidationFailed("Invalid revenue split", errors=errors)
    method = _method(rows) if rows else "percent"
    if method == "percent" and sum((r.percent or 0 for r in rows), Decimal(0)) > HUNDRED:
        raise ValidationFailed("Split over 100%", errors=[field_error("allocations", "Percentages exceed 100%")])

    await session.execute(delete(RevenueAllocation).where(RevenueAllocation.payment_entry_id == payment_id))
    session.add_all(
        RevenueAllocation(
            payment_entry_id=payment_id,
            employee_id=r.employee_id,
            project_id=r.project_id or default_project_id,
            method=method,
            percent=r.percent,
            amount_base=r.amount,
            status="draft",
        )
        for r in rows
    )
    await session.flush()
    return await for_payment(session, payment_id)


def compute(rows: list[RevenueAllocation], eligible: Decimal, precision: int) -> list[Decimal]:
    """Amounts per row. Percent splits use largest-remainder so 100% always sums exactly to `eligible`."""
    if not rows:
        return []
    if rows[0].method == "amount":
        return [quantize(r.amount_base or Decimal(0), precision) for r in rows]
    pct_total = sum((r.percent or Decimal(0) for r in rows), Decimal(0))
    covered = quantize(eligible * pct_total / HUNDRED, precision)
    return allocate(covered, [r.percent or Decimal(0) for r in rows], precision)


async def activate(
    session: AsyncSession,
    *,
    payment_id: uuid.UUID,
    eligible: Decimal,
    on: date,
    precision: int,
    require_full: bool = True,
) -> list[RevenueAllocation]:
    """The split is optional: with no rows the revenue counts toward nobody's salary. With rows, they must
    cover the eligible amount exactly (no partial splits)."""
    rows = await for_payment(session, payment_id)
    if not rows:
        return []
    inactive = set(r.employee_id for r in rows) - await employees.active_ids(session, [r.employee_id for r in rows], on)
    if inactive:
        names = await employees.names(session, list(inactive))
        raise ValidationFailed(
            "Employee not active",
            errors=[
                field_error("allocations", f"{', '.join(names.values())} not employed on {on.isoformat()}", "inactive")
            ],
        )
    amounts = compute(rows, eligible, precision)
    total = sum(amounts, Decimal(0))
    if require_full and total != eligible:
        raise ValidationFailed(
            f"The revenue split must cover exactly {eligible} (currently {total})",
            errors=[field_error("allocations", f"Split covers {total} of {eligible}", "incomplete")],
        )
    if total > eligible:
        raise ValidationFailed(
            "Split exceeds payment", errors=[field_error("allocations", "More than the eligible amount")]
        )
    for row, amount in zip(rows, amounts, strict=True):
        row.amount_base = amount
        row.status = "active"
        row.attribution_date = on
    await session.flush()
    for row in rows:
        emit(session, "attribution.changed", {"employee_id": str(row.employee_id), "date": on.isoformat()})
    return rows


async def cancel(session: AsyncSession, *, payment_id: uuid.UUID) -> None:
    rows = await for_payment(session, payment_id)
    await session.execute(
        update(RevenueAllocation)
        .where(RevenueAllocation.payment_entry_id == payment_id, RevenueAllocation.status == "active")
        .values(status="cancelled")
    )
    for row in rows:
        if row.attribution_date:
            emit(
                session,
                "attribution.changed",
                {"employee_id": str(row.employee_id), "date": row.attribution_date.isoformat()},
            )


async def copy_as_draft(session: AsyncSession, *, from_payment_id: uuid.UUID, to_payment_id: uuid.UUID) -> None:
    for r in await for_payment(session, from_payment_id):
        session.add(
            RevenueAllocation(
                payment_entry_id=to_payment_id,
                employee_id=r.employee_id,
                project_id=r.project_id,
                method=r.method,
                percent=r.percent,
                amount_base=r.amount_base if r.method == "amount" else None,
                status="draft",
            )
        )
    await session.flush()


async def proposal(session: AsyncSession, project_id: uuid.UUID) -> list[SplitIn]:
    """Pre-fill from the project's default split (docs/architecture.md, Section 8.2)."""
    return [
        SplitIn(employee_id=e, percent=p, project_id=project_id)
        for e, p in await projects.default_split(session, project_id)
    ]


async def employee_totals(
    session: AsyncSession, *, date_from: date, date_to: date, employee_ids: list[uuid.UUID] | None = None
) -> dict[uuid.UUID, Decimal]:
    stmt = (
        select(RevenueAllocation.employee_id, func.sum(RevenueAllocation.amount_base))
        .where(RevenueAllocation.status == "active", RevenueAllocation.attribution_date.between(date_from, date_to))
        .group_by(RevenueAllocation.employee_id)
    )
    if employee_ids is not None:
        stmt = stmt.where(RevenueAllocation.employee_id.in_(employee_ids))
    return dict((await session.execute(stmt)).all())


async def employee_project_totals(
    session: AsyncSession, *, date_from: date, date_to: date, employee_ids: list[uuid.UUID] | None = None
) -> list[tuple[uuid.UUID, uuid.UUID | None, Decimal, int]]:
    """(employee, project, revenue, number of payments) for active allocations in the date range."""
    stmt = (
        select(
            RevenueAllocation.employee_id,
            RevenueAllocation.project_id,
            func.sum(RevenueAllocation.amount_base),
            func.count(),
        )
        .where(RevenueAllocation.status == "active", RevenueAllocation.attribution_date.between(date_from, date_to))
        .group_by(RevenueAllocation.employee_id, RevenueAllocation.project_id)
    )
    if employee_ids is not None:
        stmt = stmt.where(RevenueAllocation.employee_id.in_(employee_ids))
    return [tuple(r) for r in (await session.execute(stmt)).all()]  # type: ignore[misc]


async def active_for_employee(
    session: AsyncSession, *, employee_id: uuid.UUID, date_from: date, date_to: date
) -> list[RevenueAllocation]:
    return list(
        (
            await session.execute(
                select(RevenueAllocation)
                .where(
                    RevenueAllocation.employee_id == employee_id,
                    RevenueAllocation.status == "active",
                    RevenueAllocation.attribution_date.between(date_from, date_to),
                )
                .order_by(RevenueAllocation.attribution_date, RevenueAllocation.created_at)
            )
        ).scalars()
    )


async def project_totals(session: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Revenue credited to employees per project (active allocations)."""
    if not project_ids:
        return {}
    rows = await session.execute(
        select(RevenueAllocation.project_id, func.sum(RevenueAllocation.amount_base))
        .where(RevenueAllocation.status == "active", RevenueAllocation.project_id.in_(project_ids))
        .group_by(RevenueAllocation.project_id)
    )
    return dict(rows.all())  # type: ignore[arg-type]
