import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.core.db import get_session
from app.core.errors import Forbidden
from app.core.pagination import Page, PageParams, page_params, paginate
from app.modules.auth.api import CurrentUser, require, require_any
from app.modules.employees import api as employees
from app.modules.projects import service
from app.modules.rbac.api import Scope

router = APIRouter(prefix="/projects", tags=["projects"])
milestones_router = APIRouter(prefix="/milestones", tags=["projects"])

Status = Literal["planned", "active", "on_hold", "completed", "cancelled"]
Priority = Literal["low", "medium", "high", "urgent"]
MilestoneStatus = Literal["planned", "in_progress", "done", "cancelled"]
Money = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=4)]
Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
Pct = Annotated[Decimal, Field(gt=0, le=100, max_digits=7, decimal_places=4)]
# Staff, plus employees running their own projects; service.edit_mode decides what each may change.
EditProjects = Depends(require_any("projects.manage", "projects.create_own"))


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: uuid.UUID
    employee_name: str | None = None
    role: str | None
    default_allocation_pct: Decimal | None


class PersonOut(BaseModel):
    id: uuid.UUID
    full_name: str


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    name: str
    customer_party_id: uuid.UUID | None
    customer_name: str | None = None
    manager_employee_id: uuid.UUID | None
    manager_name: str | None = None
    hire_employee_id: uuid.UUID | None
    hire_name: str | None = None
    project_type_category_id: uuid.UUID
    project_type_other_text: str | None
    description: str | None
    start_date: date | None
    deadline: date | None
    contract_value: Decimal | None
    budget: Decimal | None
    priority: str
    completion_override: Decimal | None
    currency: str
    status: str
    created_at: datetime
    version: int
    members: list[MemberOut] = []
    # What the signed-in user may edit: full, own (work and hire), or nothing.
    edit_mode: Literal["full", "own"] | None = None
    lapsed: bool = False  # active, but no income in the last 3 months


class MemberIn(BaseModel):
    employee_id: uuid.UUID
    role: str | None = Field(default=None, max_length=80)
    default_allocation_pct: Pct | None = None


class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    customer_party_id: uuid.UUID | None = None
    manager_employee_id: uuid.UUID | None = None
    hire_employee_id: uuid.UUID | None = None
    members: list[MemberIn] | None = Field(default=None, max_length=200)
    project_type_category_id: uuid.UUID
    project_type_other_text: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=10000)
    start_date: date | None = None
    deadline: date | None = None
    contract_value: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    budget: Money | None = None
    priority: Priority = "medium"
    completion_override: Percent | None = None
    currency: str | None = Field(default=None, max_length=10)
    status: Status = "active"


class ProjectUpdateIn(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    customer_party_id: uuid.UUID | None = None
    manager_employee_id: uuid.UUID | None = None
    hire_employee_id: uuid.UUID | None = None
    members: list[MemberIn] | None = Field(default=None, max_length=200)
    project_type_category_id: uuid.UUID | None = None
    project_type_other_text: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=10000)
    start_date: date | None = None
    deadline: date | None = None
    contract_value: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=4)
    budget: Money | None = None
    priority: Priority | None = None
    completion_override: Percent | None = None
    currency: str | None = Field(default=None, max_length=10)
    status: Status | None = None


class MembersIn(BaseModel):
    members: list[MemberIn] = Field(max_length=200)


async def _out(
    session: AsyncSession,
    user: CurrentUser,
    viewer: service.Viewer,
    project: service.Project,
    lapsed: set[uuid.UUID] | None = None,
) -> ProjectOut:
    if lapsed is None:
        lapsed = await service.lapsed_ids(session, [project])
    rows = await service.members(session, project.id)
    people = [project.manager_employee_id, project.hire_employee_id, *(m.employee_id for m in rows)]
    names = await employees.names(session, [p for p in people if p])
    members = [MemberOut.model_validate(m).model_copy(update={"employee_name": names.get(m.employee_id)}) for m in rows]
    out = ProjectOut.model_validate(project).model_copy(
        update={
            "members": members,
            "manager_name": names.get(project.manager_employee_id),
            "hire_name": names.get(project.hire_employee_id),
            "edit_mode": service.edit_mode(user, viewer, project),
            "lapsed": project.id in lapsed and not viewer.restricted,
        }
    )
    is_manager = viewer.employee_id is not None and project.manager_employee_id == viewer.employee_id
    if project.customer_party_id and (viewer.restricted or is_manager or user.can("parties.read")):
        parties = await lookup.resolve(session, "party", [project.customer_party_id])
        out.customer_name = parties.get(project.customer_party_id)
    if viewer.restricted:  # They see the work and the customer's name, never the money.
        out.customer_party_id = out.contract_value = out.budget = None
        out.members = [m.model_copy(update={"default_allocation_pct": None}) for m in members]
    return out


@router.get("", response_model=Page[ProjectOut])
async def list_projects(
    params: PageParams = Depends(page_params),
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: Status | None = None,
    customer_party_id: uuid.UUID | None = None,
    hire_employee_id: uuid.UUID | None = None,
    manager_employee_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(require("projects.read", Scope.PROJECT)),
    session: AsyncSession = Depends(get_session),
) -> Page[ProjectOut]:
    only = None if user.scope_for("projects.read") == Scope.ALL else await service.visible_project_ids(session, user)
    stmt = service.list_stmt(
        q=q,
        status=status,
        customer_party_id=customer_party_id,
        only_ids=only,
        hire_employee_id=hire_employee_id,
        manager_employee_id=manager_employee_id,
    )
    rows, total = await paginate(session, stmt, params)
    viewer = await service.viewer_for(session, user)
    lapsed = await service.lapsed_ids(session, list(rows))
    return Page(
        items=[await _out(session, user, viewer, p, lapsed) for p in rows],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.get("/my-managers", response_model=list[PersonOut])
async def my_managers(
    user: CurrentUser = Depends(require("projects.read", Scope.PROJECT)),
    session: AsyncSession = Depends(get_session),
) -> list[PersonOut]:
    """For a hire: the project managers they already work for, who a new project can be created under."""
    viewer = await service.viewer_for(session, user)
    if not viewer.is_hire or viewer.employee_id is None:
        return []
    names = await employees.names(session, list(await service.managers_of_hire(session, viewer.employee_id)))
    return [PersonOut(id=i, full_name=n) for i, n in sorted(names.items(), key=lambda x: x[1].lower())]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    user: CurrentUser = Depends(require("projects.read", Scope.PROJECT)),
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await service.get(session, project_id)
    await service.ensure_visible(session, user, "projects.read", project)
    return await _out(session, user, await service.viewer_for(session, user), project)


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreateIn,
    user: CurrentUser = EditProjects,
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await service.create_by(
        session,
        user=user,
        data=body.model_dump(exclude={"members"}),
        rows=[m.model_dump() for m in body.members] if body.members is not None else None,
    )
    await session.commit()
    return await _out(session, user, await service.viewer_for(session, user), project)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdateIn,
    user: CurrentUser = EditProjects,
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await service.get(session, project_id)
    await service.can_manage(session, user, project)
    project = await service.update_by(
        session,
        user=user,
        project=project,
        version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version", "members"}),
        rows=[m.model_dump() for m in body.members] if body.members is not None else None,
    )
    await session.commit()
    return await _out(session, user, await service.viewer_for(session, user), project)


@router.put("/{project_id}/members", response_model=ProjectOut)
async def set_members(
    project_id: uuid.UUID,
    body: MembersIn,
    user: CurrentUser = EditProjects,
    session: AsyncSession = Depends(get_session),
) -> ProjectOut:
    project = await service.get(session, project_id)
    await service.can_manage(session, user, project)
    viewer = await service.viewer_for(session, user)
    if service.edit_mode(user, viewer, project) != service.FULL:
        raise Forbidden("Only staff can change the team")
    await service.set_members(
        session, actor_id=user.id, project_id=project_id, rows=[m.model_dump() for m in body.members]
    )
    await session.commit()
    return await _out(session, user, viewer, project)


# ---- milestones ------------------------------------------------------------------------------------


class MilestoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    due_date: date | None
    status: str
    version: int


class MilestoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    due_date: date | None = None
    status: MilestoneStatus = "planned"


class MilestoneUpdateIn(BaseModel):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    due_date: date | None = None
    status: MilestoneStatus | None = None


@router.get("/{project_id}/milestones", response_model=list[MilestoneOut])
async def list_milestones(
    project_id: uuid.UUID,
    user: CurrentUser = Depends(require("projects.read", Scope.PROJECT)),
    session: AsyncSession = Depends(get_session),
) -> list[service.Milestone]:
    await service.ensure_visible(session, user, "projects.read", await service.get(session, project_id))
    return await service.milestones(session, project_id)


@router.post("/{project_id}/milestones", response_model=MilestoneOut, status_code=201)
async def create_milestone(
    project_id: uuid.UUID,
    body: MilestoneIn,
    user: CurrentUser = EditProjects,
    session: AsyncSession = Depends(get_session),
) -> service.Milestone:
    await service.can_manage_id(session, user, project_id)
    m = await service.create_milestone(session, actor_id=user.id, project_id=project_id, data=body.model_dump())
    await session.commit()
    return m


@milestones_router.patch("/{milestone_id}", response_model=MilestoneOut)
async def update_milestone(
    milestone_id: uuid.UUID,
    body: MilestoneUpdateIn,
    user: CurrentUser = EditProjects,
    session: AsyncSession = Depends(get_session),
) -> service.Milestone:
    m = await service.get_milestone(session, milestone_id)
    await service.can_manage_id(session, user, m.project_id)
    m = await service.update_milestone(
        session,
        actor_id=user.id,
        milestone_id=milestone_id,
        version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version"}),
    )
    await session.commit()
    return m


@milestones_router.delete("/{milestone_id}", status_code=204)
async def delete_milestone(
    milestone_id: uuid.UUID,
    user: CurrentUser = EditProjects,
    session: AsyncSession = Depends(get_session),
) -> Response:
    m = await service.get_milestone(session, milestone_id)
    await service.can_manage_id(session, user, m.project_id)
    await service.delete_milestone(session, actor_id=user.id, milestone_id=milestone_id)
    await session.commit()
    return Response(status_code=204)
