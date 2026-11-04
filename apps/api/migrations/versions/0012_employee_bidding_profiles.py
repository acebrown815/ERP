"""employees can have several bidding profile names: move them from a column to their own table

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-03 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employee_bidding_profiles",
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_employee_bidding_profiles_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name=op.f("fk_employee_bidding_profiles_employee_id_employees"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_employee_bidding_profiles_updated_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_employee_bidding_profiles")),
    )
    op.create_index("ix_employee_bidding_profiles_employee_id", "employee_bidding_profiles", ["employee_id"])
    op.create_index(
        "uq_employee_bidding_profiles_name",
        "employee_bidding_profiles",
        [sa.literal_column("lower(name)")],
        unique=True,
    )
    op.execute(
        """
        INSERT INTO employee_bidding_profiles (id, employee_id, name)
        SELECT gen_random_uuid(), id, bidding_profile_name FROM employees WHERE bidding_profile_name IS NOT NULL
        """
    )
    op.drop_index("uq_employees_bidding_profile_name", table_name="employees")
    op.drop_column("employees", "bidding_profile_name")


def downgrade() -> None:
    # The column holds one name per employee, so an employee with several keeps the first alphabetically.
    op.add_column("employees", sa.Column("bidding_profile_name", sa.String(length=100), nullable=True))
    op.execute(
        """
        UPDATE employees e SET bidding_profile_name = (
            SELECT p.name FROM employee_bidding_profiles p WHERE p.employee_id = e.id ORDER BY lower(p.name) LIMIT 1
        )
        """
    )
    op.create_index(
        "uq_employees_bidding_profile_name",
        "employees",
        [sa.literal_column("lower(bidding_profile_name)")],
        unique=True,
        postgresql_where=sa.text("bidding_profile_name IS NOT NULL"),
    )
    op.drop_table("employee_bidding_profiles")
