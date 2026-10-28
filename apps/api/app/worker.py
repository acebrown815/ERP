"""Background worker: processes the transactional outbox.  Run with `python -m app.worker`."""

import asyncio
import contextlib
import signal

import structlog

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.core.logging import configure_logging
from app.core.outbox import process_batch
from app.models import import_all_models

log = structlog.get_logger()


async def run() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows: rely on KeyboardInterrupt
            loop.add_signal_handler(sig, stop.set)
    log.info("worker.started")
    while not stop.is_set():
        try:
            handled = await process_batch(SessionLocal, settings.worker_batch_size)
        except Exception:
            log.exception("worker.batch_failed")
            handled = 0
        if handled == 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
    await engine.dispose()
    log.info("worker.stopped")


def main() -> None:
    configure_logging()
    import_all_models()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
