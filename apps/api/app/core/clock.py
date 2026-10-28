"""The current date in the company's time zone. Tests freeze it with `freeze(date)`."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

_frozen: date | None = None


def today(timezone: str = "UTC") -> date:
    if _frozen is not None:
        return _frozen
    return datetime.now(ZoneInfo(timezone)).date()


def freeze(on: date | None) -> None:
    global _frozen
    _frozen = on
