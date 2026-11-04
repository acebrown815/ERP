"""The snapshot cache: one per connection configuration, so saving new settings in the UI starts a fresh cache.
FastAPI dependency for requests, plus the background task that keeps it current."""

import asyncio

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal, get_session
from app.modules.bidding import store
from app.modules.bidding.cache import SnapshotCache, from_config
from app.modules.bidding.config import SourceConfig

log = structlog.get_logger()

# How often the refresher looks at the data's age; the age limit itself is the cache setting.
REFRESH_CHECK_SECONDS = 15

_cache: tuple[SourceConfig, SnapshotCache] | None = None


def _cache_for(cfg: SourceConfig) -> SnapshotCache:
    global _cache
    if _cache is None or _cache[0] != cfg:
        _cache = (cfg, from_config(cfg))
    return _cache[1]


async def get_cache(session: AsyncSession = Depends(get_session)) -> SnapshotCache:
    """Tests override it with a cache fed by fake readers."""
    return _cache_for(await store.load(session))


async def run_refresher() -> None:
    """Runs for the life of the API: loads the sheets at startup, and again each time the data reaches its age limit."""
    while True:
        try:
            async with SessionLocal() as session:
                cfg = await store.load(session)
            await _cache_for(cfg).refresh()
        except Exception:  # e.g. the database is being restored; try again on the next pass
            log.exception("bidding.refresher_failed")
        await asyncio.sleep(REFRESH_CHECK_SECONDS)
