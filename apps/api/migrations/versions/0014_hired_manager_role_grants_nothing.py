"""the Hired Manager role grants nothing by itself: access comes from the linked employee being marked as a hire

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-04 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DESCRIPTION = "Label only: access comes from the linked employee being marked as a hired manager."


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE role_id IN (SELECT id FROM roles WHERE key = 'hired_manager')
        """
    )
    op.execute(
        sa.text("UPDATE roles SET description = :description WHERE key = 'hired_manager'").bindparams(
            description=DESCRIPTION
        )
    )


def downgrade() -> None:
    pass  # the role's old grants are not restored; hires never depended on them
