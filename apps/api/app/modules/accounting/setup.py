"""Registrations this module makes with shared services at startup."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import checks
from app.modules.accounting import reports
from app.modules.accounting.models import JournalLine


async def _ledger(session: AsyncSession) -> tuple[bool, str]:
    debit, credit = (
        await session.execute(
            select(
                func.coalesce(func.sum(JournalLine.debit_base), 0), func.coalesce(func.sum(JournalLine.credit_base), 0)
            )
        )
    ).one()
    return debit == credit, f"Debits {debit:,.2f} · credits {credit:,.2f}"


async def _balance_sheet(session: AsyncSession) -> tuple[bool, str]:
    bs = await reports.balance_sheet(session, date.today())
    diff = bs.total_assets - bs.total_liabilities - bs.total_equity
    return (
        diff == 0,
        f"Assets {bs.total_assets:,.2f} = liabilities {bs.total_liabilities:,.2f} + equity {bs.total_equity:,.2f}"
        + ("" if diff == 0 else f" (off by {diff:,.2f})"),
    )


def setup() -> None:
    checks.register("ledger_balanced", "Ledger debits equal credits", _ledger)
    checks.register("balance_sheet", "Balance sheet balances", _balance_sheet)
