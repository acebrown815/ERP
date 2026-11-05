"""Background worker. Run with `python -m app.worker`.

- processes the transactional outbox continuously
- every minute: calendar reminders and "due today" task notices
- nightly (after 02:00 company time): consistency checks, then an automatic backup (Settings → Backups), removing
  automatic ones older than ERP_BACKUPS_KEEP_DAYS; administrators are notified in the app if either fails
"""

import asyncio
import contextlib
import signal
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import checks, clock
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.core.errors import NotFound
from app.core.logging import configure_logging
from app.core.outbox import process_batch
from app.models import import_all_models
from app.modules.backups import api as backups

log = structlog.get_logger()

REMINDER_EVERY_SECONDS = 60
NIGHTLY_HOUR = 2


async def reminders_job() -> int:
    from app.modules.calendar import api as calendar

    async with SessionLocal() as session:
        sent = await calendar.send_reminders(session, datetime.now(UTC))
        await session.commit()
    return sent


async def notify_admins(session: AsyncSession, *, kind: str, title: str, body: str, link: str) -> None:
    """The bell icon of every administrator, at most once a day per kind."""
    from app.modules.calendar import api as calendar
    from app.modules.rbac import api as rbac

    today = clock.today()
    for admin in await rbac.admin_user_ids(session):
        await calendar.notify(
            session,
            user_id=admin,
            kind=kind,
            title=title,
            body=body[:2000],
            link=link,
            dedupe_key=f"{kind}:{today}:{admin}",
        )


async def nightly_checks_job() -> bool:
    async with SessionLocal() as session:
        results = await checks.run_all(session)
        failed = [r for r in results if not r.ok]
        for r in results:
            (log.warning if not r.ok else log.info)("check.result", check=r.key, ok=r.ok, detail=r.detail)
        if failed:
            await notify_admins(
                session,
                kind="system_check_failed",
                title=f"{len(failed)} consistency check(s) failed",
                body="; ".join(f"{r.label}: {r.detail}" for r in failed),
                link="/settings/system",
            )
        await session.commit()
    return not failed


async def nightly_backup_job() -> None:
    try:
        await backups.nightly()
    except Exception as exc:
        log.exception("worker.backup_failed")
        async with SessionLocal() as session:
            await notify_admins(
                session,
                kind="backup_failed",
                title="Last night's backup failed",
                body=str(exc),
                link="/settings/backups",
            )
            await session.commit()


async def company_timezone() -> ZoneInfo:
    from app.modules.settings import api as settings

    async with SessionLocal() as session:
        try:
            return ZoneInfo((await settings.get_company(session)).timezone)
        except NotFound:  # a first install, before the seed
            return ZoneInfo("UTC")


def nightly_due(now: datetime, last_run: date | None) -> bool:
    """`now` is in the company's time zone."""
    return now.hour >= NIGHTLY_HOUR and last_run != now.date()


def last_nightly_run(timezone: ZoneInfo) -> date | None:
    """Survives restarts: a deploy after 02:00 must not make another backup that night."""
    newest = backups.last_automatic()
    return newest.astimezone(timezone).date() if newest else None


async def run() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows: rely on KeyboardInterrupt
            loop.add_signal_handler(sig, stop.set)
    log.info("worker.started")
    last_reminders = 0.0
    last_nightly = last_nightly_run(await company_timezone())
    while not stop.is_set():
        try:
            handled = await process_batch(SessionLocal, settings.worker_batch_size)
        except Exception:
            log.exception("worker.batch_failed")
            handled = 0
        now = loop.time()
        if now - last_reminders >= REMINDER_EVERY_SECONDS:
            last_reminders = now
            try:
                await reminders_job()
            except Exception:
                log.exception("worker.reminders_failed")
            try:
                local_now = datetime.now(await company_timezone())
                if nightly_due(local_now, last_nightly):
                    last_nightly = local_now.date()
                    try:
                        await nightly_checks_job()
                    except Exception:
                        log.exception("worker.checks_failed")
                    await nightly_backup_job()
            except Exception:
                log.exception("worker.nightly_failed")
        if handled == 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
    await engine.dispose()
    log.info("worker.stopped")


def main() -> None:
    configure_logging()
    import_all_models()
    import app.main  # noqa: F401  (building the app runs every module's setup: checks, lookups)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
