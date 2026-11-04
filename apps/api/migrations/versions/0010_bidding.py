"""bidding analytics: employees' bidding profile name (their tab in the bids sheet) and bidding.read grants

Bid and job data is not stored: the bidding module reads the Google Sheets live.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-03 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("bidding_profile_name", sa.String(length=100), nullable=True))
    op.create_index(
        "uq_employees_bidding_profile_name",
        "employees",
        [sa.literal_column("lower(bidding_profile_name)")],
        unique=True,
        postgresql_where=sa.text("bidding_profile_name IS NOT NULL"),
    )
    # Roles are seeded once and never overwritten, so existing installs get the new defaults here
    # (employees: their own numbers; project managers: everyone's). Admins already hold every permission.
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission, scope)
        SELECT id, 'bidding.read', CASE key WHEN 'employee' THEN 'own' ELSE 'all' END
        FROM roles WHERE key IN ('employee', 'project_manager')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission IN ('bidding.read', 'bidding.manage')")
    op.drop_index("uq_employees_bidding_profile_name", table_name="employees")
    op.drop_column("employees", "bidding_profile_name")
