"""Public facade of the compensation (salary formulas) module."""

from app.modules.compensation.engine import FormulaDefinition, Result, calculate
from app.modules.compensation.service import (
    Resolved,
    create_assignment,
    default_formula,
    list_assignments,
    lock_versions,
    register_closed_through,
    resolve,
    seed,
)

__all__ = [
    "FormulaDefinition",
    "Resolved",
    "Result",
    "calculate",
    "create_assignment",
    "default_formula",
    "list_assignments",
    "lock_versions",
    "register_closed_through",
    "resolve",
    "seed",
]
