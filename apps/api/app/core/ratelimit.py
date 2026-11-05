"""In-memory counters of failed password attempts, per key, over a sliding window.

The API runs as one process (apps/api/Dockerfile), so memory is enough. A restart clears the counters, and the
account-wide lock in the auth module, which is stored in the database, still applies.
"""

import time
from collections import deque

MAX_KEYS = 100_000  # an attacker sending endless made-up emails must not grow this without limit

_limiters: list["FailureLimiter"] = []


class FailureLimiter:
    def __init__(self, window_seconds: float) -> None:
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        _limiters.append(self)

    def _recent(self, key: str, now: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def count(self, key: str) -> int:
        hits = self._recent(key, time.monotonic())
        return len(hits) if hits else 0

    def hit(self, key: str) -> None:
        now = time.monotonic()
        hits = self._recent(key, now)
        if hits is None:
            if len(self._hits) >= MAX_KEYS:
                self._evict(now)
            hits = self._hits[key] = deque()
        hits.append(now)

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)

    def _evict(self, now: float) -> None:
        for key in list(self._hits):
            self._recent(key, now)
        while len(self._hits) >= MAX_KEYS:  # all still active: drop the oldest key
            del self._hits[next(iter(self._hits))]

    def reset(self) -> None:
        self._hits.clear()


def reset_all() -> None:
    """Tests: every test starts with empty counters."""
    for limiter in _limiters:
        limiter.reset()
