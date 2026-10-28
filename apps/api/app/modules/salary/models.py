import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk

RATE = Numeric(20, 12)


class SalaryPeriod(UUIDPk, Base):
    """One pay cycle, e.g. "Nov 2026" = Oct 25 – Nov 24 (docs/architecture.md, Section 10.1).

    Stored with explicit dates so history never depends on the current cycle setting. Periods are
    contiguous; an exclusion constraint (migration 0003) rules out overlaps.
    """

    __tablename__ = "salary_periods"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="dates_ordered"),
        CheckConstraint("status IN ('open', 'closed')", name="status_valid"),
    )

    label: Mapped[str] = mapped_column(String(40))
    start_date: Mapped[date] = mapped_column(unique=True)
    end_date: Mapped[date] = mapped_column(unique=True)
    # Shorter bridge period created when the cycle start day changes.
    is_transition: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(10), default="open")
    closed_at: Mapped[datetime | None]
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reopened_at: Mapped[datetime | None]
    reopened_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reopen_reason: Mapped[str | None] = mapped_column(Text)


class SalaryStatement(UUIDPk, Base):
    """Frozen result for one employee in a closed period. Open periods are calculated live, so rows
    exist only while the period is closed (reopening deletes them; the audit log keeps the old figures)."""

    __tablename__ = "salary_statements"
    __table_args__ = (UniqueConstraint("salary_period_id", "employee_id"),)

    salary_period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("salary_periods.id", ondelete="RESTRICT"))
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    formula_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("comp_formulas.id", ondelete="RESTRICT"))
    formula_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comp_formula_versions.id", ondelete="RESTRICT")
    )
    formula_name: Mapped[str | None] = mapped_column(String(120))
    formula_version_no: Mapped[int | None]
    attributed_revenue: Mapped[Decimal]
    rate_applied: Mapped[Decimal] = mapped_column(RATE)
    formula_amount: Mapped[Decimal]
    adjustments_total: Mapped[Decimal]
    calculated_amount: Mapped[Decimal]
    breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    computed_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SalaryAdjustment(UUIDPk, Base):
    """Manual bonus (+), deduction (−) or correction for one employee in one open period."""

    __tablename__ = "salary_adjustments"
    __table_args__ = (
        CheckConstraint("kind IN ('bonus', 'deduction', 'correction')", name="kind_valid"),
        CheckConstraint("amount <> 0", name="amount_non_zero"),
        CheckConstraint("kind <> 'bonus' OR amount > 0", name="bonus_positive"),
        CheckConstraint("kind <> 'deduction' OR amount < 0", name="deduction_negative"),
        Index("ix_salary_adjustments_period_employee", "salary_period_id", "employee_id"),
    )

    salary_period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("salary_periods.id", ondelete="RESTRICT"))
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(12))
    amount: Mapped[Decimal]
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SalaryPayment(UUIDPk, Base):
    """A submitted salary Payment Entry, as salary sees it. Recorded on submit, removed on cancel.

    Which period it pays is derived: payments with a target period go there first, everything else pays
    the oldest unpaid period (Section 10.3).
    """

    __tablename__ = "salary_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_salary_payments_employee", "employee_id"),
    )

    payment_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_entries.id", ondelete="RESTRICT"), unique=True
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    amount: Mapped[Decimal]  # base currency
    paid_on: Mapped[date]
    salary_period_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("salary_periods.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
