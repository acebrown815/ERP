import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk

PARTY_KINDS = ("customer", "supplier", "other", "employee")
NUMBER_PREFIX = {"customer": "CUS", "supplier": "SUP", "other": "PTY", "employee": "EMP"}


class Organization(UUIDPk, Authored, Base):
    """Real-world organization; lets a customer and a supplier record point at the same company."""

    __tablename__ = "organizations"
    __table_args__ = (Index("uq_organizations_name_lower", text("lower(legal_name)"), unique=True),)

    legal_name: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)


class Party(UUIDPk, Authored, Base):
    __tablename__ = "parties"
    __table_args__ = (
        CheckConstraint(f"kind IN {PARTY_KINDS}", name="kind_valid"),
        Index("ix_parties_kind_name", "kind", text("lower(name)")),
    )

    number: Mapped[str] = mapped_column(String(20), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    subtype_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    subtype_other_text: Mapped[str | None] = mapped_column(String(120))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    contact_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[dict[str, Any]] = mapped_column(default=dict)
    default_currency: Mapped[str | None] = mapped_column(ForeignKey("currencies.code", ondelete="RESTRICT"))
    payment_details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)
