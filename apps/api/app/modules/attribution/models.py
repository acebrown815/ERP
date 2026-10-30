import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPk


class RevenueAllocation(UUIDPk, Base):
    """Management record: which employees a customer receipt is credited to (kind revenue, counts toward
    salary), or how an expense payment is shared between employees (kind expense, reports only). Never
    touches the ledger.

    Rows follow their payment: draft while it is a draft, active once submitted, cancelled with it.
    """

    __tablename__ = "revenue_allocations"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'cancelled')", name="status_valid"),
        CheckConstraint("method IN ('percent', 'amount')", name="method_valid"),
        CheckConstraint("kind IN ('revenue', 'expense')", name="kind_valid"),
        CheckConstraint("percent IS NULL OR (percent > 0 AND percent <= 100)", name="percent_range"),
        CheckConstraint("amount_base IS NULL OR amount_base > 0", name="amount_positive"),
        CheckConstraint(
            "status <> 'active' OR (amount_base IS NOT NULL AND attribution_date IS NOT NULL)", name="active_complete"
        ),
        UniqueConstraint("payment_entry_id", "employee_id"),
        Index("ix_revenue_allocations_employee_date", "employee_id", "attribution_date"),
    )

    payment_entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payment_entries.id", ondelete="CASCADE"))
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    # Set from the payment's direction when it is submitted.
    kind: Mapped[str] = mapped_column(String(10), default="revenue", server_default="revenue")
    method: Mapped[str] = mapped_column(String(10))
    percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    # Fixed amount (method=amount) or the computed share (method=percent, set on activation).
    amount_base: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    status: Mapped[str] = mapped_column(String(10), default="draft")
    attribution_date: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
