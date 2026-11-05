import uuid
from datetime import date
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.modules.audit import api as audit
from app.modules.auth import api as auth
from app.modules.categories import api as categories
from app.modules.employees.models import Department, Employee, EmployeeBiddingProfile
from app.modules.parties import api as parties
from app.modules.rbac import api as rbac

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
    "is_hired_manager",
)


# People outside the company's staff. Their sign-ins get the restricted access in auth/deps.py, whatever role they hold.
RESTRICTED_EMPLOYMENT_TYPES = {"contractor", "freelancer"}


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


async def _employment_type(session: AsyncSession, category_id: uuid.UUID | None) -> str | None:
    return (await categories.get(session, category_id)).system_key if category_id else None


async def is_restricted(session: AsyncSession, employee: Employee) -> bool:
    """Hired managers, and anyone engaged as a contractor or freelancer."""
    if employee.is_hired_manager:
        return True
    return await _employment_type(session, employee.employment_type_category_id) in RESTRICTED_EMPLOYMENT_TYPES


async def is_full_time(session: AsyncSession, employee: Employee) -> bool:
    return not employee.is_hired_manager and (
        await _employment_type(session, employee.employment_type_category_id) == "full_time"
    )


async def hire_ids(session: AsyncSession, ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these employees are hired managers (they earn no revenue and get no salary)."""
    if not ids:
        return set()
    rows = await session.execute(select(Employee.id).where(Employee.id.in_(ids), Employee.is_hired_manager))
    return set(rows.scalars())


async def assert_not_hire(session: AsyncSession, employee_id: uuid.UUID, field: str = "employee_id") -> None:
    if await hire_ids(session, [employee_id]):
        raise ValidationFailed(
            "Not available for hired managers",
            errors=[field_error(field, "Hired managers earn no revenue or salary", "hired_manager")],
        )


async def active_hires(session: AsyncSession) -> list[Employee]:
    rows = await session.execute(
        select(Employee)
        .where(Employee.is_hired_manager, Employee.status != "terminated")
        .order_by(func.lower(Employee.full_name))
    )
    return list(rows.scalars())


async def all_hires(session: AsyncSession) -> list[Employee]:
    rows = await session.execute(
        select(Employee).where(Employee.is_hired_manager).order_by(func.lower(Employee.full_name))
    )
    return list(rows.scalars())


async def _check_hire_change(session: AsyncSession, employee: Employee) -> None:
    """An employee with money or project history can't become a hired manager, or stop being one: their past
    salary, revenue and payments only make sense as the type they had. Imported here because those modules
    depend on this one."""
    from app.modules.attribution import api as attribution
    from app.modules.compensation import api as compensation
    from app.modules.payments import api as payments
    from app.modules.projects import api as projects
    from app.modules.salary import api as salary

    reasons = []
    if await compensation.has_assignments(session, employee.id):
        reasons.append("a salary formula")
    if await attribution.has_allocations(session, employee.id):
        reasons.append("revenue or expense splits")
    if await salary.has_adjustments(session, employee.id):
        reasons.append("salary adjustments")
    if await payments.has_employee_payments(session, employee_id=employee.id, party_id=employee.party_id):
        reasons.append("payments")
    if await projects.is_on_any_project(session, employee.id):
        reasons.append("projects")
    if reasons:
        raise ValidationFailed(
            "Can't change whether this person is a hired manager",
            errors=[field_error("is_hired_manager", f"{employee.full_name} already has {', '.join(reasons)}")],
        )


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
    *,
    q: str | None,
    status: str | None,
    department_id: uuid.UUID | None,
    only_user_id: uuid.UUID | None = None,
    hired: bool | None = None,
) -> Select[tuple[Employee]]:
    stmt = select(Employee).order_by(func.lower(Employee.full_name))
    if hired is not None:
        stmt = stmt.where(Employee.is_hired_manager.is_(hired))
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
        # Restricted access is fixed, so this would silently take an administrator's away.
        employment = await _employment_type(session, data.get("employment_type_category_id"))
        restricted = bool(data.get("is_hired_manager")) or employment in RESTRICTED_EMPLOYMENT_TYPES
        if restricted and data["user_id"] in await rbac.admin_user_ids(session):
            field = "is_hired_manager" if data.get("is_hired_manager") else "employment_type_category_id"
            raise ValidationFailed(
                "An administrator can't have restricted access",
                errors=[field_error(field, "This sign-in is an administrator")],
            )
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
    merged["is_hired_manager"] = bool(merged["is_hired_manager"])
    await _validate(session, merged, employee.id)
    if merged["is_hired_manager"] != before["is_hired_manager"]:
        await _check_hire_change(session, employee)
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


# ---- bidding profile names (an employee's tabs in the bids spreadsheet) --------------------------------------


def normalize_profile_name(name: str | None) -> str | None:
    """Trim and collapse inner spaces; blank means "not set"."""
    cleaned = " ".join((name or "").split())
    return cleaned or None


async def profile_names(session: AsyncSession, employee_id: uuid.UUID) -> list[str]:
    rows = await session.execute(
        select(EmployeeBiddingProfile.name)
        .where(EmployeeBiddingProfile.employee_id == employee_id)
        .order_by(func.lower(EmployeeBiddingProfile.name))
    )
    return list(rows.scalars())


def _profile_name_taken(message: str) -> ValidationFailed:
    return ValidationFailed(
        "Bidding profile name in use", errors=[field_error("bidding_profile_names", message, "duplicate")]
    )


async def set_bidding_profile_names(
    session: AsyncSession, *, actor_id: uuid.UUID, employee_id: uuid.UUID, names: list[str]
) -> Employee:
    """Replace the employee's profile names (employees may set their own without employees.manage). Names are
    normalized and de-duplicated ignoring case; a name another employee already uses is rejected."""
    employee = await get(session, employee_id)
    wanted: dict[str, str] = {}
    for raw in names:
        name = normalize_profile_name(raw)
        if name:
            wanted.setdefault(name.lower(), name)

    if wanted:
        clash = (
            await session.execute(
                select(EmployeeBiddingProfile.name, Employee.full_name)
                .join(Employee, Employee.id == EmployeeBiddingProfile.employee_id)
                .where(
                    func.lower(EmployeeBiddingProfile.name).in_(wanted),
                    EmployeeBiddingProfile.employee_id != employee.id,
                )
                .order_by(func.lower(EmployeeBiddingProfile.name))
                .limit(1)
            )
        ).first()
        if clash:
            raise _profile_name_taken(f"“{clash[0]}” is already used by {clash[1]}")

    current = list(
        (
            await session.execute(
                select(EmployeeBiddingProfile).where(EmployeeBiddingProfile.employee_id == employee.id)
            )
        ).scalars()
    )
    before = sorted((row.name for row in current), key=str.lower)
    after = sorted(wanted.values(), key=str.lower)
    if before == after:
        return employee

    existing = {row.name.lower() for row in current}
    for row in current:
        key = row.name.lower()
        if key not in wanted:
            await session.delete(row)
        elif row.name != wanted[key]:
            row.name, row.updated_by = wanted[key], actor_id
    for key, name in wanted.items():
        if key not in existing:
            session.add(
                EmployeeBiddingProfile(employee_id=employee.id, name=name, created_by=actor_id, updated_by=actor_id)
            )
    employee.version += 1
    employee.updated_by = actor_id
    try:
        await session.flush()
    except IntegrityError as e:  # someone else claimed the same tab between the check above and this save
        raise _profile_name_taken("One of these names was just taken by another employee") from e
    await audit.record(
        session,
        actor_id=actor_id,
        action="employee.bidding_profiles_set",
        entity_type="employee",
        entity_id=employee.id,
        before={"bidding_profile_names": before},
        after={"bidding_profile_names": after},
    )
    return employee


async def bidding_profiles(session: AsyncSession) -> list[tuple[Employee, list[str]]]:
    """Every employee that is not terminated, plus terminated ones that still have profile names, with those names."""
    names: dict[uuid.UUID, list[str]] = {}
    rows = await session.execute(
        select(EmployeeBiddingProfile.employee_id, EmployeeBiddingProfile.name).order_by(
            func.lower(EmployeeBiddingProfile.name)
        )
    )
    for employee_id, name in rows:
        names.setdefault(employee_id, []).append(name)
    employees = await session.execute(
        select(Employee)
        .where(or_(Employee.status != "terminated", Employee.id.in_(select(EmployeeBiddingProfile.employee_id))))
        .order_by(func.lower(Employee.full_name))
    )
    return [(e, names.get(e.id, [])) for e in employees.scalars()]


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


async def by_ids(session: AsyncSession, ids: list[uuid.UUID]) -> list[Employee]:
    if not ids:
        return []
    return list((await session.execute(select(Employee).where(Employee.id.in_(ids)))).scalars())


async def active_in(
    session: AsyncSession, *, department_id: uuid.UUID | None = None, on: date | None = None
) -> list[Employee]:
    """Current staff (not terminated), optionally of one department."""
    stmt = select(Employee).where(Employee.status != "terminated").order_by(Employee.full_name)
    if department_id:
        stmt = stmt.where(Employee.department_id == department_id)
    if on:
        stmt = stmt.where(Employee.start_date <= on, or_(Employee.end_date.is_(None), Employee.end_date >= on))
    return list((await session.execute(stmt)).scalars())
