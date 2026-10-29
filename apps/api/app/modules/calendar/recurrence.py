"""RFC 5545 recurrence expansion (docs/architecture.md, Section 11.3). Pure: no database.

Timed events repeat by wall-clock time in their own zone, so a 09:00 Europe/Berlin weekly meeting stays at 09:00
local across daylight-saving changes (its UTC instant moves). All-day events repeat as dates.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr

MAX_OCCURRENCES = 2000
ALLOWED_KEYS = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "WKST"}


class RecurrenceError(ValueError):
    pass


@dataclass(frozen=True)
class Occurrence:
    key: str  # original start: ISO date (all-day) or ISO UTC instant; used for exceptions
    start_at: datetime | None
    end_at: datetime | None
    start_date: date | None
    end_date: date | None


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise RecurrenceError(f"Unknown time zone {name!r}") from None


def normalize(rule: str | None, *, tz: str, all_day: bool) -> str | None:
    """Validate a rule and make UNTIL unambiguous: a date-only UNTIL means "through that day" in the event's zone."""
    if not rule or not rule.strip():
        return None
    parts = {}
    for chunk in rule.strip().removeprefix("RRULE:").split(";"):
        if "=" not in chunk:
            raise RecurrenceError(f"Invalid rule part {chunk!r}")
        k, v = chunk.split("=", 1)
        k = k.upper()
        if k not in ALLOWED_KEYS:
            raise RecurrenceError(f"Unsupported rule part {k}")
        parts[k] = v.upper()
    if parts.get("FREQ") not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        raise RecurrenceError("FREQ must be DAILY, WEEKLY, MONTHLY or YEARLY")
    if "COUNT" in parts and "UNTIL" in parts:
        raise RecurrenceError("Use COUNT or UNTIL, not both")
    until = parts.get("UNTIL")
    if until and re.fullmatch(r"\d{8}", until):
        d = datetime.strptime(until, "%Y%m%d").date()
        if all_day:
            parts["UNTIL"] = d.strftime("%Y%m%d")
        else:
            end_local = datetime.combine(d, time(23, 59, 59), zone(tz))
            parts["UNTIL"] = end_local.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    elif until and not re.fullmatch(r"\d{8}T\d{6}Z", until):
        raise RecurrenceError("UNTIL must be YYYYMMDD or YYYYMMDDTHHMMSSZ")
    out = ";".join(f"{k}={v}" for k, v in parts.items())
    try:  # parse once to surface errors early
        rrulestr(out, dtstart=datetime(2000, 1, 1, tzinfo=None if all_day else zone(tz)))
    except ValueError as exc:
        raise RecurrenceError(str(exc)) from None
    return out


def expand_timed(
    start_at: datetime, end_at: datetime, tz: str, rule: str | None, window_from: datetime, window_to: datetime
) -> list[Occurrence]:
    """Occurrences overlapping [window_from, window_to) (aware datetimes)."""
    duration = end_at - start_at
    if not rule:
        if start_at < window_to and end_at > window_from:
            return [Occurrence(start_at.astimezone(UTC).isoformat(), start_at, end_at, None, None)]
        return []
    z = zone(tz)
    dtstart = start_at.astimezone(z)
    r = rrulestr(rule, dtstart=dtstart)
    out = []
    for occ in r.xafter((window_from - duration).astimezone(z), inc=True, count=MAX_OCCURRENCES):
        if occ >= window_to.astimezone(z):
            break
        s = occ.astimezone(UTC)
        out.append(Occurrence(s.isoformat(), s, s + duration, None, None))
    return out


def expand_all_day(start: date, end: date, rule: str | None, window_from: date, window_to: date) -> list[Occurrence]:
    """Occurrences overlapping [window_from, window_to] (inclusive dates)."""
    span = end - start
    if not rule:
        return (
            [Occurrence(start.isoformat(), None, None, start, end)] if start <= window_to and end >= window_from else []
        )
    r = rrulestr(rule, dtstart=datetime.combine(start, time()))
    out = []
    for occ in r.xafter(datetime.combine(window_from - span, time()), inc=True, count=MAX_OCCURRENCES):
        d = occ.date()
        if d > window_to:
            break
        out.append(Occurrence(d.isoformat(), None, None, d, d + span))
    return out


def days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
