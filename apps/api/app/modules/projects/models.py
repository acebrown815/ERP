import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk

PROJECT_STATUSES = ("planned", "active", "on_hold", "completed", "cancelled")
PRIORITIES = ("low", "medium", "high", "urgent")
MILESTONE_STATUSES = ("planned", "in_progress", "done", "cancelled")


class Project(UUIDPk, Authored, Base):
    """A customer engagement: team and default revenue split, milestones, tasks (tasks module), financials."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(f"status IN {PROJECT_STATUSES}", name="status_valid"),
        CheckConstraint("deadline IS NULL OR start_date IS NULL OR deadline >= start_date", name="dates_ordered"),
        CheckConstraint("contract_value IS NULL OR contract_value >= 0", name="contract_non_negative"),
        CheckConstraint("budget IS NULL OR budget >= 0", name="budget_non_negative"),
        CheckConstraint(f"priority IN {PRIORITIES}", name="priority_valid"),
        CheckConstraint(
            "completion_override IS NULL OR (completion_override >= 0 AND completion_override <= 100)",
            name="completion_range",
        ),
        CheckConstraint("hire_employee_id IS NULL OR hire_employee_id <> manager_employee_id", name="hire_not_manager"),
        Index("ix_projects_hire", "hire_employee_id"),
    )

    number: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    customer_party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"))
    manager_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    # The hired manager working on this project; their pay is charged to the project manager.
    hire_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    project_type_category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    project_type_other_text: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None]
    deadline: Mapped[date | None]
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    # Spending limit (expenses + salary cost), in the project currency.
    budget: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    priority: Mapped[str] = mapped_column(String(10), default="medium", server_default="medium")
    # Manual completion %; when empty it is derived from tasks (estimate-weighted share done).
    completion_override: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
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


class Milestone(UUIDPk, Authored, Base):
    __tablename__ = "milestones"
    __table_args__ = (
        CheckConstraint(f"status IN {MILESTONE_STATUSES}", name="status_valid"),
        Index("ix_milestones_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(String(20), default="planned")
    version: Mapped[int] = mapped_column(default=1)
