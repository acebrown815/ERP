"""expense splits: an expense payment can be shared between employees (reports only)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "revenue_allocations", sa.Column("kind", sa.String(length=10), server_default="revenue", nullable=False)
    )
    op.create_check_constraint(
        op.f("ck_revenue_allocations_kind_valid"), "revenue_allocations", "kind IN ('revenue', 'expense')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM revenue_allocations WHERE kind = 'expense'")
    op.drop_constraint(op.f("ck_revenue_allocations_kind_valid"), "revenue_allocations", type_="check")
    op.drop_column("revenue_allocations", "kind")
