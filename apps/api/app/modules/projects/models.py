import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk

PROJECT_STATUSES = ("planned", "active", "on_hold", "completed", "cancelled")


class Project(UUIDPk, Authored, Base):
    """Minimal in Phase 2 (enough to link payments and split revenue); tasks and timelines come in Phase 4."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(f"status IN {PROJECT_STATUSES}", name="status_valid"),
        CheckConstraint("deadline IS NULL OR start_date IS NULL OR deadline >= start_date", name="dates_ordered"),
        CheckConstraint("contract_value IS NULL OR contract_value >= 0", name="contract_non_negative"),
    )

    number: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    customer_party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"))
    manager_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    project_type_category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    project_type_other_text: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None]
    deadline: Mapped[date | None]
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), default="active")
    version: Mapped[int] = mapped_column(default=1)


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        CheckConstraint(
            "default_allocation_pct IS NULL OR (default_allocation_pct > 0 AND default_allocation_pct <= 100)",
            name="pct_range",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[str | None] = mapped_column(String(80))
    # Pre-fills the revenue split on customer payments for this project (docs/architecture.md, Section 8.2).
    default_allocation_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
