"""Time-ordered UUIDv7 identifiers (RFC 9562)."""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last = 0


def _uuid7_fallback() -> uuid.UUID:
    """Strictly increasing within the process, like Python 3.14's uuid.uuid7(): rows created in one
    transaction share created_at and are ordered by id, so ids made in the same millisecond must not
    sort randomly."""
    global _last
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76  # version
    value |= ((rand >> 62) & 0xFFF) << 64  # rand_a (12 bits)
    value |= 0b10 << 62  # variant
    value |= rand & 0x3FFF_FFFF_FFFF_FFFF  # rand_b (62 bits)
    with _lock:
        if value <= _last:
            # Same millisecond (or clock went back): continue after the previous id. Incrementing the
            # 62-bit rand_b field keeps version and variant bits intact (a carry needs 2^62 ids).
            value = _last + 1
        _last = value
    return uuid.UUID(int=value)


def new_id() -> uuid.UUID:
    native = getattr(uuid, "uuid7", None)  # Python 3.14+
    return native() if native else _uuid7_fallback()
