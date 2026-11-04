"""Public facade of the bidding module. Nothing else depends on it yet; it reads sheets, owns no tables."""

from app.modules.bidding.deps import get_cache

__all__ = ["get_cache"]
