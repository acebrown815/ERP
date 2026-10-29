"""Consistency checks over submitted payments (registered in setup)."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attribution import api as attribution
from app.modules.categories import api as categories
from app.modules.payments.models import PaymentEntry
from app.modules.salary import api as salary


async def _submitted(session: AsyncSession) -> list[PaymentEntry]:
    return list((await session.execute(select(PaymentEntry).where(PaymentEntry.status == "submitted"))).scalars())


async def _salary_purpose_ids(session: AsyncSession, rows: list[PaymentEntry]) -> set:
    out = set()
    for pid in {r.purpose_category_id for r in rows if r.purpose_category_id}:
        if (await categories.get(session, pid)).config.get("posting_rule") == "P2":
            out.add(pid)
    return out


async def revenue_splits(session: AsyncSession) -> tuple[bool, str]:
    """Every split receipt is split exactly: Σ active allocations = eligible amount."""
    rows = [r for r in await _submitted(session) if r.eligible_amount_base is not None]
    totals = await attribution.payment_totals(session, [r.id for r in rows])
    bad = [r.number for r in rows if r.id in totals and totals[r.id] != r.eligible_amount_base]
    unsplit = sum(1 for r in rows if r.id not in totals)
    detail = f"{len(rows) - unsplit} split receipts checked, {unsplit} without a split (allowed)"
    return not bad, detail + (f"; wrong total: {', '.join(bad[:10])}" if bad else "")


async def salary_links(session: AsyncSession) -> tuple[bool, str]:
    """Salary sees exactly the submitted salary payments, and every employee-tagged expense."""
    rows = await _submitted(session)
    p2 = await _salary_purpose_ids(session, rows)
    salary_ids = {r.id for r in rows if r.direction == "pay" and r.purpose_category_id in p2}
    expense_ids = {
        r.id
        for r in rows
        if r.direction == "pay"
        and r.employee_id
        and r.purpose_category_id not in p2
        and (r.base_amount or Decimal(0)) > 0
    }
    recorded_pay, recorded_exp = await salary.recorded_payment_ids(session), await salary.recorded_expense_ids(session)
    problems = []
    if recorded_pay != salary_ids:
        problems.append(f"salary payments: {len(salary_ids ^ recorded_pay)} out of step")
    if recorded_exp != expense_ids:
        problems.append(f"employee expenses: {len(expense_ids ^ recorded_exp)} out of step")
    return not problems, "; ".join(
        problems
    ) or f"{len(salary_ids)} salary payments, {len(expense_ids)} employee expenses"
