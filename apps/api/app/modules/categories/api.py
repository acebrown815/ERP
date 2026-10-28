"""Public facade of the categories module, used by every module that classifies records."""

from app.modules.categories.groups import GROUPS, OTHER
from app.modules.categories.models import Category
from app.modules.categories.service import (
    by_system_key,
    canonical_id,
    find,
    get,
    seed,
    set_config_default,
    validate_choice,
)

__all__ = [
    "GROUPS",
    "OTHER",
    "Category",
    "by_system_key",
    "canonical_id",
    "find",
    "get",
    "seed",
    "set_config_default",
    "validate_choice",
]
