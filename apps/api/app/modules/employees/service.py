import uuid
from datetime import date
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.modules.audit import api as audit
from app.modules.auth import api as auth
from app.modules.categories import api as categories
from app.modules.employees.models import Department, Employee
from app.modules.parties import api as parties

EDITABLE = (
    "full_name",
    "email",
    "phone",
    "department_id",
    "job_title",
    "employment_type_category_id",
    "employment_type_other_text",
    "status",
    "start_date",
    "end_date",
    "timezone",
    "notes",
    "user_id",
)


def _snapshot(e: Employee) -> dict[str, Any]:
    return {k: getattr(e, k) for k in EDITABLE}


async def get(session: AsyncSession, employee_id: uuid.UUID) -> Employee:
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise NotFound("Employee not found")
    return employee


async def for_user(session: AsyncSession, user_id: uuid.UUID) -> Employee | None:
    return (await session.execute(select(Employee).where(Employee.user_id == user_id))).scalar_one_or_none()


async def by_party(session: AsyncSession, party_id: uuid.UUID) -> Employee | None:
    return (await session.execute(select(Employee).where(Employee.party_id == party_id))).scalar_one_or_none()


async def names(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return dict((await session.execute(select(Employee.id, Employee.full_name).where(Employee.id.in_(ids)))).all())


async def active_ids(session: AsyncSession, ids: list[uuid.UUID], on: date) -> set[uuid.UUID]:
    """Employees employed (not terminated, started, not ended) on `on`."""
    rows = await session.execute(
        select(Employee.id).where(
            Employee.id.in_(ids),
            Employee.status != "terminated",
            Employee.start_date <= on,
            or_(Employee.end_date.is_(None), Employee.end_date >= on),
        )
    )
    return set(rows.scalars())


def list_stmt(
    *, q: str | None, status: str | None, department_id: uuid.UUID | None, only_user_id: uuid.UUID | None = None
) -> Select[tuple[Employee]]:
    stmt = select(Employee).order_by(func.lower(Employee.full_name))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Employee.full_name.ilike(like),
                Employee.email.ilike(like),
                Employee.number.ilike(like),
                Employee.job_title.ilike(like),
            )
        )
    if status:
        stmt = stmt.where(Employee.status == status)
    if department_id:
        stmt = stmt.where(Employee.department_id == department_id)
    if only_user_id is not None:
        stmt = stmt.where(Employee.user_id == only_user_id)
    return stmt


async def _validate(session: AsyncSession, data: dict[str, Any], employee_id: uuid.UUID | None = None) -> None:
    await categories.validate_choice(
        session,
        group_key="employment_type",
        category_id=data.get("employment_type_category_id"),
        other_text=data.get("employment_type_other_text"),
        field="employment_type_category_id",
        other_field="employment_type_other_text",
    )
    if data.get("department_id") and await session.get(Department, data["department_id"]) is None:
        raise ValidationFailed("Unknown department", errors=[field_error("department_id", "Not found")])
    if data.get("end_date") and data.get("start_date") and data["end_date"] < data["start_date"]:
        raise ValidationFailed("Invalid dates", errors=[field_error("end_date", "Must be on or after the start date")])
    if data.get("user_id"):
        try:
            await auth.get_user(session, data["user_id"])
        except NotFound:
            raise ValidationFailed("Unknown user", errors=[field_error("user_id", "User not found")]) from None
        other = await for_user(session, data["user_id"])
        if other and other.id != employee_id:
            raise ValidationFailed(
                "User already linked", errors=[field_error("user_id", f"Already linked to {other.full_name}")]
            )


async def create(session: AsyncSession, *, actor_id: uuid.UUID | None, data: dict[str, Any]) -> Employee:
    await _validate(session, data)
    party = await parties.create(
        session,
        actor_id=actor_id,
        kind="employee",
        data={"name": data["full_name"], "email": data.get("email"), "phone": data.get("phone")},
    )
    employee = Employee(
        number=party.number,
        party_id=party.id,
        created_by=actor_id,
        updated_by=actor_id,
        **{k: v for k, v in data.items() if k in EDITABLE},
    )
    session.add(employee)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="employee.created",
        entity_type="employee",
        entity_id=employee.id,
        after=_snapshot(employee),
    )
    return employee


async def update(
    session: AsyncSession, *, actor_id: uuid.UUID, employee_id: uuid.UUID, version: int, changes: dict[str, Any]
) -> Employee:
    employee = await get(session, employee_id)
    if employee.version != version:
        raise PreconditionFailed()
    before = _snapshot(employee)
    merged = {**before, **changes}
    await _validate(session, merged, employee.id)
    for k in EDITABLE:
        setattr(employee, k, merged[k])
    employee.version += 1
    employee.updated_by = actor_id
    # Keep the financial party in sync with the person's name and contact details.
    await parties.update(
        session,
        actor_id=actor_id,
        party_id=employee.party_id,
        version=None,
        changes={
            "name": employee.full_name,
            "email": employee.email,
            "phone": employee.phone,
            "is_active": employee.status != "terminated",
        },
        kinds=("employee",),
    )
    await session.flush()
    b, a = audit.diff(before, _snapshot(employee))
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="employee.updated",
            entity_type="employee",
            entity_id=employee.id,
            before=b,
            after=a,
        )
    return employee


# ---- departments -----------------------------------------------------------------------------------


async def list_departments(session: AsyncSession) -> list[Department]:
    return list((await session.execute(select(Department).order_by(func.lower(Department.name)))).scalars())


async def create_department(session: AsyncSession, *, actor_id: uuid.UUID, name: str) -> Department:
    if (
        await session.execute(select(Department.id).where(func.lower(Department.name) == name.strip().lower()))
    ).first():
        raise Conflict("A department with this name already exists")
    dept = Department(name=name.strip(), created_by=actor_id, updated_by=actor_id)
    session.add(dept)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="department.created",
        entity_type="department",
        entity_id=dept.id,
        after={"name": dept.name},
    )
    return dept


async def rename_department(
    session: AsyncSession, *, actor_id: uuid.UUID, department_id: uuid.UUID, name: str
) -> Department:
    dept = await session.get(Department, department_id)
    if dept is None:
        raise NotFound("Department not found")
    clash = (
        await session.execute(
            select(Department.id).where(func.lower(Department.name) == name.strip().lower(), Department.id != dept.id)
        )
    ).first()
    if clash:
        raise Conflict("A department with this name already exists")
    old = dept.name
    dept.name = name.strip()
    dept.updated_by = actor_id
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="department.renamed",
        entity_type="department",
        entity_id=dept.id,
        before={"name": old},
        after={"name": dept.name},
    )
    return dept


async def find_by_email(session: AsyncSession, email: str) -> Employee | None:
    return (
        await session.execute(select(Employee).where(func.lower(Employee.email) == email.strip().lower()).limit(1))
    ).scalar_one_or_none()


async def department_by_name(session: AsyncSession, name: str) -> Department | None:
    return (
        await session.execute(select(Department).where(func.lower(Department.name) == name.strip().lower()))
    ).scalar_one_or_none()
