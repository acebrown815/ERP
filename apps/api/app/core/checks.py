"""Consistency checks (docs/architecture.md, Section 17 "Reconciliation"). Each module registers checks over its
own data at startup; `run_all` runs them for the System checks page and the worker's nightly job."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

CheckFn = Callable[[AsyncSession], Awaitable[tuple[bool, str]]]
_checks: list[tuple[str, str, CheckFn]] = []


@dataclass
class CheckResult:
    key: str
    label: str
    ok: bool
    detail: str


def register(key: str, label: str, fn: CheckFn) -> None:
    if all(k != key for k, _, _ in _checks):
        _checks.append((key, label, fn))


async def run_all(session: AsyncSession) -> list[CheckResult]:
    out = []
    for key, label, fn in _checks:
        try:
            ok, detail = await fn(session)
        except Exception as exc:  # a failing check must not hide the others
            log.exception("check.crashed", check=key)
            ok, detail = False, f"Check failed to run: {exc}"
        out.append(CheckResult(key, label, ok, detail))
    return out
