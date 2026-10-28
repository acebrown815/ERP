"""Public facade of the salary module."""

from app.modules.salary.service import (
    assert_open,
    balances,
    ensure_covering,
    period_for,
    project_salary,
    project_weights,
    record_expense,
    record_payment,
    remove_expense,
    remove_payment,
)

__all__ = [
    "assert_open",
    "balances",
    "ensure_covering",
    "period_for",
    "project_salary",
    "project_weights",
    "record_expense",
    "record_payment",
    "remove_expense",
    "remove_payment",
]
