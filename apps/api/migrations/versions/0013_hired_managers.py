"""hired managers: flag on employees, hire on projects, and grants for the new permissions

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-04 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Seeding never changes existing roles, so grants on them are added here. A new database has no roles yet and
# gets the same grants from rbac/defaults.py.
GRANTS = (
    ("employee", "hired_managers.read", "own"),
    ("employee", "projects.create_own", "own"),
    ("finance_manager", "hired_managers.read", "all"),
)


def upgrade() -> None:
    op.add_column("employees", sa.Column("is_hired_manager", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("projects", sa.Column("hire_employee_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_projects_hire_employee_id_employees"),
        "projects",
        "employees",
        ["hire_employee_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_projects_hire_not_manager"),
        "projects",
        "hire_employee_id IS NULL OR hire_employee_id <> manager_employee_id",
    )
    op.create_index("ix_projects_hire", "projects", ["hire_employee_id"])
    for role, permission, scope in GRANTS:
        op.execute(
            sa.text(
                """
                INSERT INTO role_permissions (role_id, permission, scope)
                SELECT id, :permission, :scope FROM roles WHERE key = :role
                ON CONFLICT DO NOTHING
                """
            ).bindparams(role=role, permission=permission, scope=scope)
        )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission IN ('hired_managers.read', 'projects.create_own', 'payments.read_own')
        """
    )
    op.drop_index("ix_projects_hire", table_name="projects")
    op.drop_constraint(op.f("ck_projects_hire_not_manager"), "projects", type_="check")
    op.drop_constraint(op.f("fk_projects_hire_employee_id_employees"), "projects", type_="foreignkey")
    op.drop_column("projects", "hire_employee_id")
    op.drop_column("employees", "is_hired_manager")
