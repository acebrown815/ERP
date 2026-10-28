import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk

TASK_STATUSES = ("backlog", "todo", "in_progress", "review", "done")
TASK_PRIORITIES = ("low", "medium", "high", "urgent")


class Task(UUIDPk, Authored, Base):
    """Work item on a project. Kanban column = status, order within it = board_rank (docs/architecture.md, 11.2)."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(f"status IN {TASK_STATUSES}", name="status_valid"),
        CheckConstraint(f"priority IN {TASK_PRIORITIES}", name="priority_valid"),
        CheckConstraint("due_date IS NULL OR start_date IS NULL OR due_date >= start_date", name="dates_ordered"),
        CheckConstraint("estimate_hours IS NULL OR estimate_hours >= 0", name="estimate_non_negative"),
        CheckConstraint("parent_task_id IS NULL OR parent_task_id <> id", name="not_own_parent"),
        Index("ix_tasks_project_status_rank", "project_id", "status", "board_rank"),
        Index("ix_tasks_parent", "parent_task_id"),
    )

    number: Mapped[str] = mapped_column(String(20), unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("milestones.id", ondelete="SET NULL"))
    task_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    task_category_other_text: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="todo")
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    start_date: Mapped[date | None]
    due_date: Mapped[date | None]
    estimate_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    # Lexicographic position within the status column; a drag rewrites only the moved task.
    board_rank: Mapped[str] = mapped_column(String(64))
    completed_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(default=1)


class TaskAssignee(Base):
    __tablename__ = "task_assignees"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"), primary_key=True)


class TaskDependency(Base):
    """Finish-to-start: `task_id` can start once `depends_on_task_id` is done. No cycles (checked on insert)."""

    __tablename__ = "task_dependencies"
    __table_args__ = (CheckConstraint("task_id <> depends_on_task_id", name="not_self"),)

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)


class TimeEntry(UUIDPk, Base):
    __tablename__ = "time_entries"
    __table_args__ = (
        CheckConstraint("hours > 0 AND hours <= 24", name="hours_range"),
        Index("ix_time_entries_task", "task_id"),
        Index("ix_time_entries_employee_date", "employee_id", "work_date"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="RESTRICT"))
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    work_date: Mapped[date]
    hours: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TaskComment(UUIDPk, Base):
    __tablename__ = "task_comments"
    __table_args__ = (Index("ix_task_comments_task", "task_id", "created_at"),)

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    edited_at: Mapped[datetime | None]
