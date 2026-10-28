import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk

ROOT_TYPES = ("asset", "liability", "equity", "income", "expense")

# Account types allowed under each root type. Payment accounts may only map to the "money" types.
ACCOUNT_TYPES: dict[str, tuple[str, ...]] = {
    "asset": ("bank", "cash", "crypto_wallet", "current_asset", "fixed_asset", "other_asset"),
    "liability": ("credit_card", "current_liability", "other_liability"),
    "equity": ("equity",),
    "income": ("income",),
    "expense": ("expense",),
}
MONEY_ACCOUNT_TYPES = ("bank", "cash", "crypto_wallet", "credit_card")

# Debit-normal roots show positive balances when debits exceed credits.
DEBIT_NORMAL = ("asset", "expense")

BASE = Numeric(20, 4)
QUANTITY = Numeric(38, 18)
RATE = Numeric(30, 12)


class Account(UUIDPk, Authored, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(f"root_type IN {ROOT_TYPES}", name="root_type_valid"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        Index("uq_accounts_system_key", "system_key", unique=True, postgresql_where=text("system_key IS NOT NULL")),
        Index("ix_accounts_path", "path", postgresql_ops={"path": "text_pattern_ops"}),
    )

    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    # Materialized path of ids ("/<id>/<id>/"), so a subtree is `path LIKE '<parent path>%'`.
    path: Mapped[str] = mapped_column(Text)
    root_type: Mapped[str] = mapped_column(String(20))
    account_type: Mapped[str] = mapped_column(String(30))
    is_group: Mapped[bool] = mapped_column(default=False)
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code", ondelete="RESTRICT"))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)
    # Accounts the posting rules rely on (e.g. salary_expense, fx_gain_loss). They can be renamed, not removed.
    system_key: Mapped[str | None] = mapped_column(String(50))
    version: Mapped[int] = mapped_column(default=1)


class AccountingPeriod(UUIDPk, Base):
    __tablename__ = "accounting_periods"
    __table_args__ = (
        UniqueConstraint("start_date"),
        CheckConstraint("end_date >= start_date", name="dates_ordered"),
        CheckConstraint("status IN ('open', 'closed')", name="status_valid"),
    )

    start_date: Mapped[date]
    end_date: Mapped[date]
    status: Mapped[str] = mapped_column(String(10), default="open")
    closed_at: Mapped[datetime | None]
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class JournalEntry(UUIDPk, Base):
    """Posted on insert. Never edited: the only allowed change is posted -> reversed (database trigger)."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint("status IN ('posted', 'reversed')", name="status_valid"),
        CheckConstraint("entry_type IN ('manual', 'payment', 'opening', 'reversal')", name="entry_type_valid"),
        Index(
            "uq_journal_entries_source",
            "source_type",
            "source_id",
            "entry_type",
            unique=True,
            postgresql_where=text("source_id IS NOT NULL"),
        ),
        Index("ix_journal_entries_posting_date", "posting_date"),
    )

    number: Mapped[str] = mapped_column(String(30), unique=True)
    posting_date: Mapped[date]
    period_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounting_periods.id", ondelete="RESTRICT"))
    entry_type: Mapped[str] = mapped_column(String(20))
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[uuid.UUID | None]
    source_number: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(10), default="posted")
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("journal_entries.id", ondelete="RESTRICT"))
    reversed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("journal_entries.id", ondelete="RESTRICT"))
    memo: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime]
    posted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class JournalLine(UUIDPk, Base):
    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint("debit_base >= 0 AND credit_base >= 0", name="non_negative"),
        CheckConstraint("(debit_base = 0) <> (credit_base = 0)", name="one_sided"),
        UniqueConstraint("journal_entry_id", "line_no"),
        Index("ix_journal_lines_account", "account_id", "journal_entry_id"),
        Index("ix_journal_lines_party", "party_id", postgresql_where=text("party_id IS NOT NULL")),
        Index("ix_journal_lines_project", "project_id", postgresql_where=text("project_id IS NOT NULL")),
        Index("ix_journal_lines_employee", "employee_id", postgresql_where=text("employee_id IS NOT NULL")),
    )

    journal_entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("journal_entries.id", ondelete="RESTRICT"))
    line_no: Mapped[int]
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    debit_base: Mapped[Decimal] = mapped_column(BASE, default=Decimal(0))
    credit_base: Mapped[Decimal] = mapped_column(BASE, default=Decimal(0))
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code", ondelete="RESTRICT"))
    # Signed amount in the account's currency (positive = debit).
    amount_in_currency: Mapped[Decimal] = mapped_column(QUANTITY)
    exchange_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal(1))
    # Dimension tags. Plain uuids: the referenced modules own their tables and validate on their side.
    party_id: Mapped[uuid.UUID | None]
    project_id: Mapped[uuid.UUID | None]
    employee_id: Mapped[uuid.UUID | None]
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    description: Mapped[str | None] = mapped_column(Text)
