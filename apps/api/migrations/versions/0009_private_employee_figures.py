"""employees never see colleagues' money: revenue.read is own or all; whole-project financials are all-only

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A project scope showed teammates' attributed revenue; narrow it to their own.
    op.execute("UPDATE role_permissions SET scope = 'own' WHERE permission = 'revenue.read' AND scope = 'project'")
    # Project totals include the team's salary; only whole-business roles keep them.
    op.execute("DELETE FROM role_permissions WHERE permission = 'projects.read_financials' AND scope <> 'all'")


def downgrade() -> None:
    pass  # narrowed grants are not widened back; re-grant them under Settings > Roles if needed
