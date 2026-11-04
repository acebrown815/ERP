import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFound
from app.core.pagination import Page, PageParams, page_params, paginate
from app.modules.auth.api import CurrentUser, current_user, require
from app.modules.employees import service
from app.modules.employees.models import Employee
from app.modules.rbac.api import Scope

router = APIRouter(tags=["employees"])

Status = Literal["active", "on_leave", "terminated"]


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    party_id: uuid.UUID
    user_id: uuid.UUID | None
    full_name: str
    email: str | None
    phone: str | None
    department_id: uuid.UUID | None
    job_title: str | None
    employment_type_category_id: uuid.UUID
    employment_type_other_text: str | None
    status: str
    start_date: date
    end_date: date | None
    timezone: str | None
    notes: str | None
    created_at: datetime
    version: int


class EmployeeDetailOut(EmployeeOut):
    bidding_profile_names: list[str]


class EmployeeCreateIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    department_id: uuid.UUID | None = None
    job_title: str | None = Field(default=None, max_length=120)
    employment_type_category_id: uuid.UUID
    employment_type_other_text: str | None = Field(default=None, max_length=120)
    status: Status = "active"
    start_date: date
    end_date: date | None = None
    timezone: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=5000)
    user_id: uuid.UUID | None = None


class EmployeeUpdateIn(BaseModel):
    version: int
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    department_id: uuid.UUID | None = None
    job_title: str | None = Field(default=None, max_length=120)
    employment_type_category_id: uuid.UUID | None = None
    employment_type_other_text: str | None = Field(default=None, max_length=120)
    status: Status | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=5000)
    user_id: uuid.UUID | None = None


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


async def _scope_filter(session: AsyncSession, user: CurrentUser) -> tuple[uuid.UUID | None, set[uuid.UUID] | None]:
    """(only this user's record, or only these employee ids) depending on the employees.read scope."""
    from app.modules.projects import api as projects

    scope = user.scope_for("employees.read")
    if scope == Scope.ALL:
        return None, None
    if scope == Scope.PROJECT:
        ids = await projects.team_ids(session, await projects.visible_project_ids(session, user))
        own = await service.for_user(session, user.id)
        if own:
            ids.add(own.id)
        return None, ids
    return user.id, None


@router.get("/employees", response_model=Page[EmployeeOut])
async def list_employees(
    params: PageParams = Depends(page_params),
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: Status | None = None,
    department_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(require("employees.read")),
    session: AsyncSession = Depends(get_session),
) -> Page[EmployeeOut]:
    only_user, only_ids = await _scope_filter(session, user)
    stmt = service.list_stmt(q=q, status=status, department_id=department_id, only_user_id=only_user)
    if only_ids is not None:
        stmt = stmt.where(Employee.id.in_(only_ids))
    rows, total = await paginate(session, stmt, params)
    return Page(
        items=[EmployeeOut.model_validate(r) for r in rows], total=total, page=params.page, page_size=params.page_size
    )


@router.get("/employees/me", response_model=EmployeeOut)
async def my_employee(user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)) -> Any:
    employee = await service.for_user(session, user.id)
    if employee is None:
        raise NotFound("Your user is not linked to an employee record")
    return employee


@router.get("/employees/{employee_id}", response_model=EmployeeDetailOut)
async def get_employee(
    employee_id: uuid.UUID,
    user: CurrentUser = Depends(require("employees.read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    employee = await service.get(session, employee_id)
    only_user, only_ids = await _scope_filter(session, user)
    if (only_user and employee.user_id != only_user) or (only_ids is not None and employee.id not in only_ids):
        raise NotFound("Employee not found")
    return EmployeeDetailOut(
        **EmployeeOut.model_validate(employee).model_dump(),
        bidding_profile_names=await service.profile_names(session, employee.id),
    )


@router.post("/employees", response_model=EmployeeOut, status_code=201)
async def create_employee(
    body: EmployeeCreateIn,
    actor: CurrentUser = Depends(require("employees.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    employee = await service.create(session, actor_id=actor.id, data=body.model_dump())
    await session.commit()
    return employee


@router.patch("/employees/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeUpdateIn,
    actor: CurrentUser = Depends(require("employees.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    employee = await service.update(
        session,
        actor_id=actor.id,
        employee_id=employee_id,
        version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )
    await session.commit()
    return employee


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(_: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)) -> Any:
    return await service.list_departments(session)


@router.post("/departments", response_model=DepartmentOut, status_code=201)
async def create_department(
    body: DepartmentIn,
    actor: CurrentUser = Depends(require("employees.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    dept = await service.create_department(session, actor_id=actor.id, name=body.name)
    await session.commit()
    return dept


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
async def rename_department(
    department_id: uuid.UUID,
    body: DepartmentIn,
    actor: CurrentUser = Depends(require("employees.manage")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    dept = await service.rename_department(session, actor_id=actor.id, department_id=department_id, name=body.name)
    await session.commit()
    return dept
