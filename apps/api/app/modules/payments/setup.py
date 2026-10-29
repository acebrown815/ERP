"""Registrations this module makes with shared services at startup."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import checks, lookup
from app.modules.attachments import api as attachments
from app.modules.auth.api import CurrentUser
from app.modules.payments import checks as payment_checks
from app.modules.payments.models import PaymentEntry


async def _can_read(_: AsyncSession, user: CurrentUser, __: str) -> bool:
    return user.can("payments.create") or user.can("reports.financial")


async def _can_write(_: AsyncSession, user: CurrentUser, __: str) -> bool:
    return user.can("payments.create")


async def _numbers(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = await session.execute(select(PaymentEntry.id, PaymentEntry.number).where(PaymentEntry.id.in_(ids)))
    return dict(rows.all())  # type: ignore[arg-type]


def setup() -> None:
    lookup.register("payment_entry", _numbers)
    checks.register("revenue_splits", "Revenue splits match their receipts", payment_checks.revenue_splits)
    checks.register(
        "salary_links", "Salary records match salary payments and employee expenses", payment_checks.salary_links
    )
    attachments.register_entity("payment_entry", can_read=_can_read, can_write=_can_write)
