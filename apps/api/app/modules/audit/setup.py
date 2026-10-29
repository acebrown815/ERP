"""Registrations this module makes with shared services at startup."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import checks
from app.core.outbox import OutboxEvent
from app.modules.audit.service import verify_chain


async def _chain(session: AsyncSession) -> tuple[bool, str]:
    ok, broken, checked = await verify_chain(session)
    return ok, f"{checked} entries verified" if ok else f"Chain broken at entry {broken} (of {checked} checked)"


async def _outbox(session: AsyncSession) -> tuple[bool, str]:
    stale = (
        await session.execute(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.processed_at.is_(None), OutboxEvent.created_at < datetime.now(UTC) - timedelta(minutes=15)
            )
        )
    ).scalar_one()
    return (
        stale == 0,
        "Background worker is keeping up"
        if stale == 0
        else f"{stale} events waiting over 15 minutes: is the worker running?",
    )


def setup() -> None:
    checks.register("audit_chain", "Audit log is untampered", _chain)
    checks.register("worker", "Background worker", _outbox)
