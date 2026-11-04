"""bidding settings: the two Apps Script web apps, editable under Settings → Bidding Sheets

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-03 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bidding_settings",
        sa.Column("singleton", sa.Boolean(), nullable=False),
        sa.Column("bids_webapp_url", sa.String(length=500), nullable=True),
        sa.Column("bids_secret", sa.String(length=500), nullable=True),
        sa.Column("jobs_webapp_url", sa.String(length=500), nullable=True),
        sa.Column("jobs_token", sa.String(length=500), nullable=True),
        sa.Column("jobs_tabs", sa.Text(), nullable=True),
        sa.Column("cache_seconds", sa.SmallInteger(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("singleton", name=op.f("ck_bidding_settings_singleton_true")),
        sa.CheckConstraint(
            "cache_seconds IS NULL OR cache_seconds BETWEEN 30 AND 3600", name=op.f("ck_bidding_settings_cache_range")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_bidding_settings_created_by_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_bidding_settings_updated_by_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bidding_settings")),
        sa.UniqueConstraint("singleton", name=op.f("uq_bidding_settings_singleton")),
    )


def downgrade() -> None:
    op.drop_table("bidding_settings")
