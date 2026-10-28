"""Registrations this module makes with shared services at startup."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.modules.compensation import api as compensation
from app.modules.salary.models import SalaryPeriod
from app.modules.salary.service import closed_through


async def _labels(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = await session.execute(select(SalaryPeriod.id, SalaryPeriod.label).where(SalaryPeriod.id.in_(ids)))
    return dict(rows.all())  # type: ignore[arg-type]


def setup() -> None:
    lookup.register("salary_period", _labels)
    # Formula versions and assignments can't change dates covered by closed periods.
    compensation.register_closed_through(closed_through)
