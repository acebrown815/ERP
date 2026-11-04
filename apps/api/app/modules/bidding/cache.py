"""Keeps the latest Snapshot in memory for a few minutes. Nothing is written to the database.

- Requests are answered from memory. Only the very first load, or a forced refresh, waits for Google; older data
  is returned straight away while a new read runs in the background. deps.run_refresher keeps it current.
- Concurrent requests share one fetch (single flight).
- If one web app fails, its previous data is kept and the error is reported; the other side still refreshes.
- A forced refresh is ignored when the snapshot is younger than MIN_REFRESH_SECONDS.
"""

import asyncio
import functools
import time
from collections.abc import Callable
from datetime import UTC, datetime

import structlog

from app.modules.bidding import snapshot as snap
from app.modules.bidding.config import SourceConfig
from app.modules.bidding.sheets import BidsClient, BidTab, JobsClient, JobTab, SheetsError, WebApp

log = structlog.get_logger()

MIN_REFRESH_SECONDS = 15

BidsReader = Callable[[], list[BidTab]]
JobsReader = Callable[[], list[JobTab]]


class SnapshotCache:
    def __init__(
        self,
        *,
        bids_reader: BidsReader | None,
        jobs_reader: JobsReader | None,
        ttl_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.bids_reader, self.jobs_reader = bids_reader, jobs_reader
        self.ttl = ttl_seconds
        self._monotonic, self._now = monotonic, now
        self._lock: asyncio.Lock | None = None
        self._refreshing: asyncio.Task[None] | None = None
        self._snapshot: snap.Snapshot | None = None
        self._loaded_at = 0.0
        self._bid_tabs: list[BidTab] = []
        self._job_tabs: list[JobTab] = []
        self._bids_state = snap.SourceState(configured=bids_reader is not None)
        self._jobs_state = snap.SourceState(configured=jobs_reader is not None)

    def _fresh(self, max_age: float) -> bool:
        return self._snapshot is not None and self._monotonic() - self._loaded_at < max_age

    async def get(self, *, force: bool = False) -> snap.Snapshot:
        if not force and self._snapshot is not None:
            if not self._fresh(self.ttl):
                self._refresh_in_background()
            return self._snapshot
        await self._load_unless_fresh(MIN_REFRESH_SECONDS if force else self.ttl)
        assert self._snapshot is not None
        return self._snapshot

    async def refresh(self) -> None:
        """Read the sheets if the data has reached its age limit. Does nothing while it is still fresh."""
        await self._load_unless_fresh(self.ttl)

    async def _load_unless_fresh(self, max_age: float) -> None:
        if self._fresh(max_age):
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if not self._fresh(max_age):  # another request may have just loaded it
                await self._load()

    def _refresh_in_background(self) -> None:
        if self._refreshing is None or self._refreshing.done():
            self._refreshing = asyncio.create_task(self._refresh_logged())

    async def _refresh_logged(self) -> None:
        try:
            await self.refresh()
        except Exception:
            log.exception("bidding.refresh_failed")

    async def _read[T](
        self, reader: Callable[[], list[T]] | None, state: snap.SourceState, label: str
    ) -> list[T] | None:
        if reader is None:
            return None
        try:
            result = await asyncio.to_thread(reader)
        except SheetsError as e:
            state.error = str(e)
            log.warning("bidding.read_failed", source=label, error=str(e))
            return None
        except Exception as e:  # never let a sheet problem take the page down
            state.error = f"unexpected error: {e}"
            log.exception("bidding.read_failed", source=label)
            return None
        state.error = None
        state.fetched_at = self._now()
        return result

    async def _load(self) -> None:
        bid_tabs, job_tabs = await asyncio.gather(
            self._read(self.bids_reader, self._bids_state, "bids"),
            self._read(self.jobs_reader, self._jobs_state, "jobs"),
        )
        if bid_tabs is not None:
            self._bid_tabs = bid_tabs
            self._bids_state.tabs_read = [t.name for t in bid_tabs]
        if job_tabs is not None:
            self._job_tabs = job_tabs
            self._jobs_state.tabs_read = [t.name for t in job_tabs]
        # Joining thousands of rows takes a moment; a worker thread keeps other requests moving meanwhile.
        self._snapshot = await asyncio.to_thread(
            snap.build,
            self._bid_tabs,
            self._job_tabs,
            now=self._now(),
            bids_source=snap.SourceState(**vars(self._bids_state) | {"tabs_read": list(self._bids_state.tabs_read)}),
            jobs_source=snap.SourceState(**vars(self._jobs_state) | {"tabs_read": list(self._jobs_state.tabs_read)}),
        )
        self._loaded_at = self._monotonic()
        log.info(
            "bidding.sheets_read",
            bids=len(self._snapshot.bids),
            jobs=len(self._snapshot.jobs),
            bids_error=bool(self._bids_state.error),
            jobs_error=bool(self._jobs_state.error),
        )


def job_tab_names(raw: str) -> list[str]:
    return [n.strip() for n in raw.split(",") if n.strip()]


def from_config(cfg: SourceConfig) -> SnapshotCache:
    bids_reader: BidsReader | None = None
    jobs_reader: JobsReader | None = None
    if cfg.bids_configured:
        bids_reader = BidsClient(WebApp(cfg.bids_url, timeout=cfg.timeout_seconds), cfg.bids_secret).read_all
    if cfg.jobs_configured:
        jobs = JobsClient(WebApp(cfg.jobs_url, timeout=cfg.timeout_seconds), cfg.jobs_token)
        jobs_reader = functools.partial(jobs.read_tabs, list(cfg.jobs_tabs))
    return SnapshotCache(bids_reader=bids_reader, jobs_reader=jobs_reader, ttl_seconds=cfg.cache_seconds)
