"""Salary period date arithmetic (docs/architecture.md, Section 10.1). Pure functions, no database.

A cycle start day d (1-28) gives periods d → (d-1) of the next month; d = 1 is the calendar month.
A period is labelled by the month it ends in: with d = 25, "Nov 2026" is Oct 25 – Nov 24.
"""

from dataclasses import dataclass
from datetime import date, timedelta

ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Span:
    start: date
    end: date
    is_transition: bool = False

    @property
    def label(self) -> str:
        base = self.end.strftime("%b %Y")
        return f"{base} (transition)" if self.is_transition else base


def _add_month(d: date) -> date:
    """Same day next month. Safe because cycle days are 1-28."""
    return date(d.year + d.month // 12, d.month % 12 + 1, d.day)


def _sub_month(d: date) -> date:
    return date(d.year - (1 if d.month == 1 else 0), 12 if d.month == 1 else d.month - 1, d.day)


def regular(day: int, containing: date) -> Span:
    """The regular period that contains `containing`."""
    if not 1 <= day <= 28:
        raise ValueError("cycle start day must be 1-28")
    start = date(containing.year, containing.month, day)
    if containing.day < day:
        start = _sub_month(start)
    return Span(start, _add_month(start) - ONE_DAY)


def next_after(previous_end: date, day: int) -> Span:
    """The period that follows one ending on `previous_end`. If the previous period doesn't line up with
    `day` (the setting changed), this is a shorter transition period up to the day before `day`."""
    start = previous_end + ONE_DAY
    if start.day == day:
        return regular(day, start)
    boundary = date(start.year, start.month, day)
    if start.day > day:
        boundary = _add_month(boundary)
    return Span(start, boundary - ONE_DAY, is_transition=True)


def previous_before(first_start: date, day: int) -> Span:
    """The period just before one starting on `first_start`, ending the day before it."""
    end = first_start - ONE_DAY
    r = regular(day, end)
    return Span(r.start, end, is_transition=end != r.end)


def upcoming(previous_end: date, day: int, count: int) -> list[Span]:
    out = []
    for _ in range(count):
        span = next_after(previous_end, day)
        out.append(span)
        previous_end = span.end
    return out
