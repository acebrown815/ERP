"""Salary periods as report columns: the company's "month" (Settings > Salary Cycle)."""

import bisect
import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.salary import api as salary
from app.modules.settings import api as settings

ZERO = Decimal(0)


class PeriodCol(BaseModel):
    id: uuid.UUID
    label: str
    start_date: date
    end_date: date
    status: str
    in_progress: bool  # the current period: its numbers are "so far"


async def recent_periods(session: AsyncSession, count: int | None) -> tuple[list[PeriodCol], date]:
    """The last `count` started periods (None: all of them), oldest first, and today (company time zone)."""
    today = await settings.today(session)
    started = [p for p in await salary.list_periods(session) if p.start_date <= today][:count]
    cols = [
        PeriodCol(
            id=p.id,
            label=p.label,
            start_date=p.start_date,
            end_date=p.end_date,
            status=p.status,
            in_progress=p.end_date >= today,
        )
        for p in reversed(started)
    ]
    return cols, today


def bucketer(periods: list[PeriodCol]) -> Callable[[date], int | None]:
    """Maps a date to its period's index, or None when outside every period."""
    starts = [p.start_date for p in periods]

    def index(day: date) -> int | None:
        i = bisect.bisect_right(starts, day) - 1
        return i if i >= 0 and day <= periods[i].end_date else None

    return index


def pct(part: Decimal, whole: Decimal) -> Decimal | None:
    return (part * 100 / whole).quantize(Decimal("0.1")) if whole else None


def completed(periods: list[PeriodCol]) -> list[int]:
    """Indexes of periods that have ended (comparisons and averages skip the one in progress)."""
    return [i for i, p in enumerate(periods) if not p.in_progress]
