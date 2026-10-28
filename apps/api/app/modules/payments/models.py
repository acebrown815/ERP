import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk

DIRECTIONS = ("receive", "pay", "internal_transfer")
STATUSES = ("draft", "submitted", "cancelled")

QUANTITY = Numeric(38, 18)
RATE = Numeric(30, 12)
BASE = Numeric(20, 4)


class PaymentAccount(UUIDPk, Authored, Base):
    """Where money sits (Company Checking, Petty Cash, USDT Wallet...). Always backed by one ledger account."""

    __tablename__ = "payment_accounts"
    __table_args__ = (Index("uq_payment_accounts_name_lower", text("lower(name)"), unique=True),)

    name: Mapped[str] = mapped_column(String(120))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), unique=True)
    kind: Mapped[str] = mapped_column(String(20))  # mirrors the ledger account type
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code", ondelete="RESTRICT"))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)  # bank name, masked IBAN, wallet address...
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)


class PaymentEntry(UUIDPk, Authored, Base):
    """Draft -> Submitted (the payment happened; posted to the ledger) -> Cancelled (reversed)."""

    __tablename__ = "payment_entries"
    __table_args__ = (
        CheckConstraint(f"direction IN {DIRECTIONS}", name="direction_valid"),
        CheckConstraint(f"status IN {STATUSES}", name="status_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("fee_amount >= 0", name="fee_non_negative"),
        CheckConstraint("fee_paid_by IN ('client', 'company')", name="fee_paid_by_valid"),
        CheckConstraint("status <> 'submitted' OR journal_entry_id IS NOT NULL", name="submitted_posted"),
        Index("ix_payment_entries_date", "posting_date"),
        Index("ix_payment_entries_party", "party_id"),
        Index("ix_payment_entries_project", "project_id"),
    )

    number: Mapped[str] = mapped_column(String(30), unique=True)
    posting_date: Mapped[date]
    direction: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(12), default="draft")

    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"))
    # Optional on drafts; required to submit.
    method_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    method_other_text: Mapped[str | None] = mapped_column(String(120))
    purpose_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    purpose_other_text: Mapped[str | None] = mapped_column(String(120))
    # Income category (receive) or expense category (pay).
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    category_other_text: Mapped[str | None] = mapped_column(String(120))

    paid_from_payment_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_accounts.id", ondelete="RESTRICT")
    )
    paid_to_payment_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payment_accounts.id", ondelete="RESTRICT")
    )
    # Explicit income/expense/equity account; when empty it is resolved from purpose, category or project type.
    counter_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))

    amount: Mapped[Decimal] = mapped_column(QUANTITY)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code", ondelete="RESTRICT"))
    exchange_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal(1))
    # Internal transfers only: what arrived on the destination side.
    received_amount: Mapped[Decimal | None] = mapped_column(QUANTITY)
    received_currency: Mapped[str | None] = mapped_column(ForeignKey("currencies.code", ondelete="RESTRICT"))
    received_exchange_rate: Mapped[Decimal | None] = mapped_column(RATE)
    fee_amount: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal(0))
    fee_paid_by: Mapped[str] = mapped_column(String(10), default="company")

    # Frozen at submit.
    base_amount: Mapped[Decimal | None] = mapped_column(BASE)
    eligible_amount_base: Mapped[Decimal | None] = mapped_column(BASE)

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    reference_no: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)

    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("journal_entries.id", ondelete="RESTRICT"))
    reversal_journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    amended_from_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_entries.id", ondelete="RESTRICT"))
    submitted_at: Mapped[datetime | None]
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    cancelled_at: Mapped[datetime | None]
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    reconciled_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(default=1)
