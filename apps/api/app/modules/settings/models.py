from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk


class Currency(Base):
    __tablename__ = "currencies"
    __table_args__ = (CheckConstraint("precision BETWEEN 0 AND 18", name="precision_range"),)

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    symbol: Mapped[str | None] = mapped_column(String(10))
    precision: Mapped[int] = mapped_column(SmallInteger)
    is_crypto: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)


class ExchangeRate(UUIDPk, Authored, Base):
    """Units of `to_currency` per one unit of `from_currency` on `rate_date`."""

    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("from_currency", "to_currency", "rate_date"),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("from_currency <> to_currency", name="distinct_currencies"),
    )

    from_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code", ondelete="RESTRICT"))
    to_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code", ondelete="RESTRICT"))
    rate_date: Mapped[date]
    rate: Mapped[Decimal] = mapped_column(Numeric(30, 12))
    source: Mapped[str] = mapped_column(String(30), default="manual")


class CompanySettings(UUIDPk, Authored, Base):
    """Single row (enforced by the unique `singleton` column)."""

    __tablename__ = "company_settings"
    __table_args__ = (
        CheckConstraint("singleton", name="singleton_true"),
        CheckConstraint("fiscal_year_start_month BETWEEN 1 AND 12", name="fiscal_month_range"),
        CheckConstraint("salary_cycle_start_day BETWEEN 1 AND 28", name="salary_cycle_day_range"),
    )

    singleton: Mapped[bool] = mapped_column(default=True, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[dict[str, Any]] = mapped_column(default=dict)
    base_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code", ondelete="RESTRICT"))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    fiscal_year_start_month: Mapped[int] = mapped_column(SmallInteger, default=1)
    salary_cycle_start_day: Mapped[int] = mapped_column(SmallInteger, default=1)
    policies: Mapped[dict[str, Any]] = mapped_column(default=dict)
    version: Mapped[int] = mapped_column(default=1)
    # Set once the first journal entry is posted (Phase 2); after that the base currency is frozen.
    base_currency_locked: Mapped[bool] = mapped_column(default=False)
