"""Lexicographic ranks for Kanban ordering. `between(a, b)` returns a string strictly between a and b, so moving
a card rewrites only that card. Ranks never end in "0", which keeps a gap open on both sides."""

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)


def between(a: str | None, b: str | None) -> str:
    """A rank after `a` and before `b` (either may be None: start / end of the column)."""
    lo = a or ""
    hi = b
    if hi is not None and lo >= hi:
        raise ValueError(f"ranks out of order: {lo!r} >= {hi!r}")
    out = []
    i = 0
    while True:
        ca = ALPHABET.index(lo[i]) if i < len(lo) else 0
        cb = ALPHABET.index(hi[i]) if hi is not None and i < len(hi) else BASE
        if ca == cb:
            out.append(ALPHABET[ca])
            i += 1
            continue
        mid = (ca + cb) // 2
        if mid > ca:
            return "".join(out) + ALPHABET[mid]
        # Adjacent digits: keep a's digit and continue with no upper bound after it.
        out.append(ALPHABET[ca])
        hi = None
        i += 1


def first() -> str:
    return between(None, None)
