"""Public facade of the categories module, used by every module that classifies records."""

from app.modules.categories.groups import GROUPS, OTHER
from app.modules.categories.service import by_system_key, canonical_id, seed, validate_choice

__all__ = ["GROUPS", "OTHER", "by_system_key", "canonical_id", "seed", "validate_choice"]
