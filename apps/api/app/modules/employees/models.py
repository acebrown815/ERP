import uuid
from datetime import date

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk

EMPLOYEE_STATUSES = ("active", "on_leave", "terminated")


class Department(UUIDPk, Authored, Base):
    __tablename__ = "departments"
    __table_args__ = (Index("uq_departments_name_lower", text("lower(name)"), unique=True),)

    name: Mapped[str] = mapped_column(String(120))


class Employee(UUIDPk, Authored, Base):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(f"status IN {EMPLOYEE_STATUSES}", name="status_valid"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="dates_ordered"),
        Index("uq_employees_user", "user_id", unique=True, postgresql_where=text("user_id IS NOT NULL")),
    )

    number: Mapped[str] = mapped_column(String(20), unique=True)
    # Financial counterpart used on salary payments and ledger lines.
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"), unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(50))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id", ondelete="RESTRICT"))
    job_title: Mapped[str | None] = mapped_column(String(120))
    employment_type_category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    employment_type_other_text: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="active")
    start_date: Mapped[date]
    end_date: Mapped[date | None]
    timezone: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
    # Someone an employee hires to help run a project: they sign in and work on projects, but earn no revenue
    # and get no salary. They are paid through project expenses (docs/hired-managers-plan.md).
    is_hired_manager: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    version: Mapped[int] = mapped_column(default=1)


class EmployeeBiddingProfile(UUIDPk, Authored, Base):
    """One of an employee's tabs in the bids spreadsheet (BidExtension "Sheet Tab Name"); see the bidding module.
    A tab belongs to one employee at most; an employee can have several."""

    __tablename__ = "employee_bidding_profiles"
    __table_args__ = (
        Index("uq_employee_bidding_profiles_name", text("lower(name)"), unique=True),
        Index("ix_employee_bidding_profiles_employee_id", "employee_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
