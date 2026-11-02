"""Background worker. Run with `python -m app.worker`.

- processes the transactional outbox continuously
- every minute: calendar reminders and "due today" task notices
- nightly (after 02:00 company time): consistency checks; administrators are notified of any failure;
  then an automatic backup (Settings → Backups), removing automatic ones older than ERP_BACKUPS_KEEP_DAYS
"""

import asyncio
import contextlib
import signal
from datetime import UTC, date, datetime

import structlog

from app.core import checks, clock
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
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


async def nightly_checks_job() -> bool:
    from app.modules.calendar import api as calendar
    from app.modules.rbac import api as rbac

    async with SessionLocal() as session:
        results = await checks.run_all(session)
        failed = [r for r in results if not r.ok]
        for r in results:
            (log.warning if not r.ok else log.info)("check.result", check=r.key, ok=r.ok, detail=r.detail)
        if failed:
            today = clock.today()
            for admin in await rbac.admin_user_ids(session):
                await calendar.notify(
                    session,
                    user_id=admin,
                    kind="system_check_failed",
                    title=f"{len(failed)} consistency check(s) failed",
                    body="; ".join(f"{r.label}: {r.detail}" for r in failed)[:2000],
                    link="/settings/system",
                    dedupe_key=f"checks:{today}:{admin}",
                )
        await session.commit()
    return not failed


async def run() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows: rely on KeyboardInterrupt
            loop.add_signal_handler(sig, stop.set)
    log.info("worker.started")
    last_reminders = 0.0
    last_nightly: date | None = None
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
        today = clock.today()
        if datetime.now().hour >= NIGHTLY_HOUR and last_nightly != today:
            last_nightly = today
            try:
                await nightly_checks_job()
            except Exception:
                log.exception("worker.checks_failed")
            try:
                await backups.nightly()
            except Exception:
                log.exception("worker.backup_failed")
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
