from sqlalchemy import CheckConstraint, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk


class BiddingSettings(UUIDPk, Authored, Base):
    """Where the bidding pages read from (Settings → Bidding Sheets). Single row. Configuration only: bid and job
    data stays in the Google Sheets. Blank fields fall back to the ERP_BIDS_* / ERP_JOBS_* environment variables.
    The secret and token are never returned by the API."""

    __tablename__ = "bidding_settings"
    __table_args__ = (
        CheckConstraint("singleton", name="singleton_true"),
        CheckConstraint("cache_seconds IS NULL OR cache_seconds BETWEEN 30 AND 3600", name="cache_range"),
    )

    singleton: Mapped[bool] = mapped_column(default=True, unique=True)
    bids_webapp_url: Mapped[str | None] = mapped_column(String(500))
    bids_secret: Mapped[str | None] = mapped_column(String(500))
    jobs_webapp_url: Mapped[str | None] = mapped_column(String(500))
    jobs_token: Mapped[str | None] = mapped_column(String(500))
    jobs_tabs: Mapped[str | None] = mapped_column(Text)  # comma-separated tab names
    cache_seconds: Mapped[int | None] = mapped_column(SmallInteger)
    version: Mapped[int] = mapped_column(default=1)
