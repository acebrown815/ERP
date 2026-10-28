import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk


class CompFormula(UUIDPk, Authored, Base):
    """A named salary plan, e.g. "Revenue Share 2026". Its rules live in versions."""

    __tablename__ = "comp_formulas"
    __table_args__ = (Index("uq_comp_formulas_name_lower", text("lower(name)"), unique=True),)

    name: Mapped[str] = mapped_column(String(120))
    compensation_type_category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT")
    )
    compensation_type_other_text: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)


class CompFormulaVersion(UUIDPk, Base):
    """Immutable rules from `effective_from` on. Editing a formula adds a version. A version used by a
    closed salary period is locked: it can't be deleted, so closed months always reproduce."""

    __tablename__ = "comp_formula_versions"
    __table_args__ = (
        UniqueConstraint("formula_id", "version_no"),
        UniqueConstraint("formula_id", "effective_from"),
    )

    formula_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("comp_formulas.id", ondelete="CASCADE"))
    version_no: Mapped[int]
    definition: Mapped[dict[str, Any]]
    effective_from: Mapped[date]
    notes: Mapped[str | None] = mapped_column(Text)
    is_locked: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CompAssignment(UUIDPk, Authored, Base):
    """Employee X is paid by formula Y over [effective_from, effective_to]. No overlaps per employee
    (exclusion constraint in migration 0003)."""

    __tablename__ = "comp_assignments"
    __table_args__ = (
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="dates_ordered"),
        Index("ix_comp_assignments_employee", "employee_id"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    formula_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("comp_formulas.id", ondelete="RESTRICT"))
    effective_from: Mapped[date]
    effective_to: Mapped[date | None]
    notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)
