"""Public facade of the salary module."""

from app.modules.salary.service import (
    assert_open,
    balances,
    ensure_covering,
    expense_totals,
    has_adjustments,
    list_periods,
    net_revenue,
    period_for,
    project_salary,
    project_weights,
    record_expense,
    record_payment,
    recorded_expense_ids,
    recorded_payment_ids,
    remove_expense,
    remove_payment,
)

__all__ = [
    "assert_open",
    "balances",
    "ensure_covering",
    "expense_totals",
    "has_adjustments",
    "list_periods",
    "net_revenue",
    "period_for",
    "project_salary",
    "project_weights",
    "record_expense",
    "record_payment",
    "recorded_expense_ids",
    "recorded_payment_ids",
    "remove_expense",
    "remove_payment",
]
