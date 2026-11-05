import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lookup
from app.core.db import get_session
from app.core.errors import Forbidden, ValidationFailed, field_error
from app.core.pagination import Page, PageParams, page_params, paginate
from app.modules.auth.api import CurrentUser, require
from app.modules.employees import api as employees
from app.modules.projects import api as projects
from app.modules.rbac.api import Scope
from app.modules.settings import api as settings
from app.modules.tasks import service
from app.modules.tasks.models import Task

router = APIRouter(tags=["tasks"])

Status = Literal["backlog", "todo", "in_progress", "review", "done"]
Priority = Literal["low", "medium", "high", "urgent"]
Hours = Annotated[Decimal, Field(ge=0, le=10000, max_digits=8, decimal_places=2)]
ReadProjects = Depends(require("projects.read", Scope.PROJECT))


# ---- schemas ---------------------------------------------------------------------------------------


class Ref(BaseModel):
    id: uuid.UUID
    name: str


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    project_id: uuid.UUID
    parent_task_id: uuid.UUID | None
    milestone_id: uuid.UUID | None
    task_category_id: uuid.UUID | None
    task_category_other_text: str | None
    title: str
    description: str | None
    status: str
    priority: str
    start_date: date | None
    due_date: date | None
    estimate_hours: Decimal | None
    board_rank: str
    completed_at: datetime | None
    created_at: datetime
    version: int
    project_name: str | None = None
    assignees: list[Ref] = []
    depends_on: list[uuid.UUID] = []
    subtasks: int = 0
    subtasks_done: int = 0
    logged_hours: Decimal = Decimal(0)
    can_edit: bool = False  # all fields (task managers)
    can_move: bool = False  # status / board position (managers and assignees)


class DependencyRef(BaseModel):
    id: uuid.UUID
    number: str
    title: str
    status: str
    due_date: date | None


class TaskDetailOut(TaskOut):
    milestone_name: str | None = None
    parent: DependencyRef | None = None
    dependencies: list[DependencyRef] = []
    blocking: list[DependencyRef] = []  # tasks waiting for this one
    children: list[TaskOut] = []


class TaskCreateIn(BaseModel):
    project_id: uuid.UUID
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    status: Status = "todo"
    priority: Priority = "medium"
    start_date: date | None = None
    due_date: date | None = None
    estimate_hours: Hours | None = None
    milestone_id: uuid.UUID | None = None
    parent_task_id: uuid.UUID | None = None
    task_category_id: uuid.UUID | None = None
    task_category_other_text: str | None = Field(default=None, max_length=120)
    assignee_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class TaskUpdateIn(BaseModel):
    version: int
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    status: Status | None = None
    priority: Priority | None = None
    start_date: date | None = None
    due_date: date | None = None
    estimate_hours: Hours | None = None
    milestone_id: uuid.UUID | None = None
    parent_task_id: uuid.UUID | None = None
    task_category_id: uuid.UUID | None = None
    task_category_other_text: str | None = Field(default=None, max_length=120)
    assignee_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)


class MoveIn(BaseModel):
    version: int
    status: Status
    before_id: uuid.UUID | None = None  # card above the drop position
    after_id: uuid.UUID | None = None  # card below the drop position


class DependencyIn(BaseModel):
    depends_on_task_id: uuid.UUID


class TimeEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    employee_id: uuid.UUID
    work_date: date
    hours: Decimal
    note: str | None
    created_at: datetime
    employee_name: str | None = None


class TimeEntryIn(BaseModel):
    work_date: date
    hours: Annotated[Decimal, Field(gt=0, le=24, max_digits=5, decimal_places=2)]
    note: str | None = Field(default=None, max_length=2000)
    employee_id: uuid.UUID | None = None  # default: yourself


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    author_user_id: uuid.UUID
    body: str
    created_at: datetime
    edited_at: datetime | None
    author_name: str | None = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


class ProgressOut(BaseModel):
    project_id: uuid.UUID
    total: int
    done: int
    percent: Decimal  # task-derived; a project's completion_override wins in the UI
    estimate_hours: Decimal
    logged_hours: Decimal
    overdue: int


class TimelineTask(BaseModel):
    id: uuid.UUID
    number: str
    title: str
    status: str
    priority: str
    parent_task_id: uuid.UUID | None
    milestone_id: uuid.UUID | None
    start_date: date | None
    due_date: date | None
    progress: Decimal  # 100 when done, else logged / estimate (capped at 95)
    assignees: list[Ref]
    depends_on: list[uuid.UUID]
    delayed: bool
    version: int


class TimelineMilestone(BaseModel):
    id: uuid.UUID
    name: str
    due_date: date | None
    status: str


class TimelineOut(BaseModel):
    project_id: uuid.UUID
    project_name: str
    start_date: date | None
    deadline: date | None
    today: date
    tasks: list[TimelineTask]
    milestones: list[TimelineMilestone]
    can_edit: bool


# ---- access ----------------------------------------------------------------------------------------


class Access:
    def __init__(
        self,
        can_manage: bool,
        employee_id: uuid.UUID | None,
        may_update_own: bool,
        team_assignees_only: bool = False,
    ) -> None:
        self.can_manage = can_manage
        self.employee_id = employee_id
        self.may_update_own = may_update_own
        # Hires, and employees running their own project, assign tasks within the project team only.
        self.team_assignees_only = team_assignees_only


async def _access(session: AsyncSession, user: CurrentUser, project_id: uuid.UUID) -> Access:
    """Read access is required (404 otherwise). Managing = tasks.manage for this project."""
    project = await projects.get(session, project_id)
    await projects.ensure_visible(session, user, "projects.read", project)
    scope = user.scope_for("tasks.manage")
    member = await projects.is_team_member(session, user, project_id)
    own = await employees.for_user(session, user.id)
    runs_own_project = (
        own is not None
        and not user.restricted
        and scope is None
        and user.can("projects.create_own")
        and project.manager_employee_id == own.id
    )
    manage = scope == Scope.ALL or (scope is not None and member) or runs_own_project
    return Access(manage, own.id if own else None, user.can("tasks.update_own"), runs_own_project or user.restricted)


async def _check_assignees(
    session: AsyncSession, access: Access, project_id: uuid.UUID, assignee_ids: list[uuid.UUID] | None
) -> None:
    if not access.team_assignees_only or not assignee_ids:
        return
    if set(assignee_ids) - await projects.team_ids(session, {project_id}):
        raise ValidationFailed(
            "Assign tasks to the project team",
            errors=[field_error("assignee_ids", "Only people on this project can be assigned")],
        )


async def _can_move(session: AsyncSession, access: Access, task: Task) -> bool:
    return access.can_manage or (
        access.may_update_own
        and access.employee_id is not None
        and await service.is_assignee(session, task.id, access.employee_id)
    )


async def _outs(session: AsyncSession, user: CurrentUser, tasks: list[Task]) -> list[TaskOut]:
    ids = [t.id for t in tasks]
    who = await service.assignees(session, ids)
    deps = await service.dependencies(session, ids)
    subs = await service.subtask_counts(session, ids)
    logged = await service.hours_logged(session, ids)
    names = await employees.names(session, list({e for es in who.values() for e in es}))
    pnames = await projects.names(session, list({t.project_id for t in tasks}))
    access: dict[uuid.UUID, Access] = {}
    out = []
    for t in tasks:
        if t.project_id not in access:
            access[t.project_id] = await _access(session, user, t.project_id)
        a = access[t.project_id]
        o = TaskOut.model_validate(t)
        o.project_name = pnames.get(t.project_id)
        o.assignees = [Ref(id=e, name=names.get(e, "?")) for e in who.get(t.id, [])]
        o.depends_on = deps.get(t.id, [])
        o.subtasks, o.subtasks_done = subs.get(t.id, (0, 0))
        o.logged_hours = logged.get(t.id, Decimal(0))
        o.can_edit = a.can_manage
        o.can_move = a.can_manage or (a.may_update_own and a.employee_id in who.get(t.id, []))
        out.append(o)
    return out


def _ref(t: Task) -> DependencyRef:
    return DependencyRef(id=t.id, number=t.number, title=t.title, status=t.status, due_date=t.due_date)


async def _detail(session: AsyncSession, user: CurrentUser, task: Task) -> TaskDetailOut:
    base = (await _outs(session, user, [task]))[0]
    out = TaskDetailOut(**base.model_dump())
    if task.milestone_id:
        out.milestone_name = (await projects.get_milestone(session, task.milestone_id)).name
    if task.parent_task_id:
        out.parent = _ref(await service.get(session, task.parent_task_id))
    out.dependencies = [_ref(await service.get(session, d)) for d in base.depends_on]
    blocking = (await session.execute(service.blocking_stmt(task.id))).scalars()
    out.blocking = [_ref(t) for t in blocking]
    children = list((await session.execute(service.list_stmt(project_ids=None, parent_task_id=task.id))).scalars())
    out.children = await _outs(session, user, children)
    return out


# ---- tasks -----------------------------------------------------------------------------------------


@router.get("/tasks", response_model=Page[TaskOut])
async def list_tasks(
    params: PageParams = Depends(page_params),
    project_id: uuid.UUID | None = None,
    assignee: Annotated[str | None, Query(description="'me' or an employee id")] = None,
    status: Annotated[list[Status] | None, Query()] = None,
    milestone_id: uuid.UUID | None = None,
    top_level: bool = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
    user: CurrentUser = ReadProjects,
    session: AsyncSession = Depends(get_session),
) -> Page[TaskOut]:
    visible = (
        None if user.scope_for("projects.read") == Scope.ALL else await projects.visible_project_ids(session, user)
    )
    assignee_id = None
    if assignee == "me":
        own = await employees.for_user(session, user.id)
        if own is None:
            return Page(items=[], total=0, page=params.page, page_size=params.page_size)
        assignee_id = own.id
    elif assignee:
        assignee_id = uuid.UUID(assignee)
    stmt = service.list_stmt(
        project_ids=visible,
        project_id=project_id,
        assignee_id=assignee_id,
        status=list(status) if status else None,
        milestone_id=milestone_id,
        top_level=top_level,
        q=q,
    )
    rows, total = await paginate(session, stmt, params)
    return Page(items=await _outs(session, user, list(rows)), total=total, page=params.page, page_size=params.page_size)


@router.get("/tasks/progress", response_model=list[ProgressOut])
async def task_progress(
    project_ids: Annotated[list[uuid.UUID], Query(max_length=200)],
    user: CurrentUser = ReadProjects,
    session: AsyncSession = Depends(get_session),
) -> list[ProgressOut]:
    if user.scope_for("projects.read") != Scope.ALL:
        visible = await projects.visible_project_ids(session, user)
        project_ids = [p for p in project_ids if p in visible]
    progress = await service.progress(session, project_ids, await settings.today(session))
    return [ProgressOut(project_id=pid, **vars(p)) for pid, p in progress.items()]


@router.get("/tasks/{task_id}", response_model=TaskDetailOut)
async def get_task(
    task_id: uuid.UUID, user: CurrentUser = ReadProjects, session: AsyncSession = Depends(get_session)
) -> TaskDetailOut:
    task = await service.get(session, task_id)
    await _access(session, user, task.project_id)
    return await _detail(session, user, task)


@router.post("/tasks", response_model=TaskDetailOut, status_code=201)
async def create_task(
    body: TaskCreateIn, user: CurrentUser = ReadProjects, session: AsyncSession = Depends(get_session)
) -> TaskDetailOut:
    access = await _access(session, user, body.project_id)
    if not access.can_manage:
        raise Forbidden("Only the project's managers can add tasks")
    await _check_assignees(session, access, body.project_id, body.assignee_ids)
    task = await service.create(
        session,
        actor_id=user.id,
        project_id=body.project_id,
        data=body.model_dump(exclude={"project_id", "assignee_ids"}),
        assignee_ids=body.assignee_ids,
    )
    await session.commit()
    return await _detail(session, user, task)


@router.patch("/tasks/{task_id}", response_model=TaskDetailOut)
async def update_task(
    task_id: uuid.UUID,
    body: TaskUpdateIn,
    user: CurrentUser = ReadProjects,
    session: AsyncSession = Depends(get_session),
) -> TaskDetailOut:
    task = await service.get(session, task_id)
    access = await _access(session, user, task.project_id)
    changes = body.model_dump(exclude_unset=True, exclude={"version", "assignee_ids"})
    # Assignees (without tasks.manage) may only move their own task along: status, nothing else.
    own_status_only = not (set(changes) - {"status"}) and body.assignee_ids is None
    if not access.can_manage and not (own_status_only and await _can_move(session, access, task)):
        raise Forbidden("You can only change the status of tasks assigned to you")
    await _check_assignees(session, access, task.project_id, body.assignee_ids)
    task = await service.update(
        session,
        actor_id=user.id,
        task_id=task_id,
        version=body.version,
        changes=changes,
        assignee_ids=body.assignee_ids,
    )
    await session.commit()
    return await _detail(session, user, task)


@router.post("/tasks/{task_id}/move", response_model=TaskOut)
async def move_task(
    task_id: uuid.UUID, body: MoveIn, user: CurrentUser = ReadProjects, session: AsyncSession = Depends(get_session)
) -> TaskOut:
    task = await service.get(session, task_id)
    access = await _access(session, user, task.project_id)
    if not await _can_move(session, access, task):
        raise Forbidden("You can only move tasks assigned to you")
    task = await service.move(
        session,
        actor_id=user.id,
        task_id=task_id,
        version=body.version,
        status=body.status,
        before_id=body.before_id,
        after_id=body.after_id,
    )
    await session.commit()
    return (await _outs(session, user, [task]))[0]


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: uuid.UUID, user: CurrentUser = ReadProjects, session: AsyncSession = Depends(get_session)
) -> Response:
    task = await service.get(session, task_id)
    if not (await _access(session, user, task.project_id)).can_manage:
        raise Forbidden("Only the project's managers can delete tasks")
    await service.delete_task(session, actor_id=user.id, task_id=task_id)
    await session.commit()
    return Response(status_code=204)


@router.post("/tasks/{task_id}/dependencies", response_model=TaskDetailOut)
async def add_dependency(
    task_id: uuid.UUID,
    body: DependencyIn,
    user: CurrentUser = ReadProjects,
    session: AsyncSession = Depends(get_session),
) -> TaskDetailOut:
    task = await service.get(session, task_id)
    if not (await _access(session, user, task.project_id)).can_manage:
        raise Forbidden("Only the project's managers can change dependencies")
    await service.add_dependency(session, actor_id=user.id, task_id=task_id, depends_on_id=body.depends_on_task_id)
    await session.commit()
    return await _detail(session, user, task)


@router.delete("/tasks/{task_id}/dependencies/{depends_on_id}", response_model=TaskDetailOut)
async def remove_dependency(
    task_id: uuid.UUID,
    depends_on_id: uuid.UUID,
    user: CurrentUser = ReadProjects,
    session: AsyncSession = Depends(get_session),
) -> TaskDetailOut:
    task = await service.get(session, task_id)
    if not (await _access(session, user, task.project_id)).can_manage:
        raise Forbidden("Only the project's managers can change dependencies")
    await service.remove_dependency(session, actor_id=user.id, task_id=task_id, depends_on_id=depends_on_id)
    await session.commit()
    return await _detail(session, user, task)


# ---- time ------------------------------------------------------------------------------------------


@router.get("/tasks/{task_id}/time-entries", response_model=list[TimeEntryOut])
async def list_time(
    task_id: uuid.UUID, user: CurrentUser = ReadProjects, session: AsyncSession = Depends(get_session)
) -> list[TimeEntryOut]:
    task = await service.get(session, task_id)
    await _access(session, user, task.project_id)
    rows = await service.time_entries(session, task_id)
    names = await employees.names(session, list({r.employee_id for r in rows}))
    return [TimeEntryOut.model_validate(r).model_copy(update={"employee_name": names.get(r.employee_id)}) for r in rows]


@router.post("/tasks/{task_id}/time-entries", response_model=TimeEntryOut, status_code=201)
async def log_time(
    task_id: uuid.UUID,
    body: TimeEntryIn,
    user: CurrentUser = ReadProjects,
    session: AsyncSession = Depends(get_session),
) -> TimeEntryOut:
    task = await service.get(session, task_id)
    access = await _access(session, user, task.project_id)
    employee_id = body.employee_id or access.employee_id
    if employee_id is None:
        raise Forbidden("Your user isn't linked to an employee; choose whose time this is")
    own = employee_id == access.employee_id
    if not access.can_manage and not (own and await _can_move(session, access, task)):
        raise Forbidden("You can log time only on tasks assigned to you")
    entry = await service.log_time(
        session,
        actor_id=user.id,
        task_id=task_id,
        employee_id=employee_id,
        work_date=body.work_date,
        hours=body.hours,
        note=body.note,
    )
    await session.commit()
    names = await employees.names(session, [employee_id])
    return TimeEntryOut.model_validate(entry).model_copy(update={"employee_name": names.get(employee_id)})


@router.delete("/time-entries/{entry_id}", status_code=204)
async def delete_time(
    entry_id: uuid.UUID, user: CurrentUser = ReadProjects, session: AsyncSession = Depends(get_session)
) -> Response:
    entry = await service.get_time_entry(session, entry_id)
    task = await service.get(session, entry.task_id)
    access = await _access(session, user, task.project_id)
    if not access.can_manage and entry.employee_id != access.employee_id:
        raise Forbidden("You can delete only your own time")
    await service.delete_time_entry(session, entry_id=entry_id)
    await session.commit()
    return Response(status_code=204)


# ---- comments --------------------------------------------------------------------------------------


async def _comment_outs(session: AsyncSession, rows: list[Any]) -> list[CommentOut]:
    names = await lookup.resolve(session, "user", (r.author_user_id for r in rows))
    return [CommentOut.model_validate(r).model_copy(update={"author_name": names.get(r.author_user_id)}) for r in rows]


@router.get("/tasks/{task_id}/comments", response_model=list[CommentOut])
async def list_comments(
    task_id: uuid.UUID, user: CurrentUser = ReadProjects, session: AsyncSession = Depends(get_session)
) -> list[CommentOut]:
    task = await service.get(session, task_id)
    await _access(session, user, task.project_id)
    return await _comment_outs(session, await service.comments(session, task_id))


@router.post("/tasks/{task_id}/comments", response_model=CommentOut, status_code=201)
async def add_comment(
    task_id: uuid.UUID, body: CommentIn, user: CurrentUser = ReadProjects, session: AsyncSession = Depends(get_session)
) -> CommentOut:
    """Anyone who can see the project can comment."""
    task = await service.get(session, task_id)
    await _access(session, user, task.project_id)
    c = await service.add_comment(session, author_id=user.id, task_id=task_id, body=body.body)
    await session.commit()
    return (await _comment_outs(session, [c]))[0]


@router.delete("/task-comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: uuid.UUID, user: CurrentUser = ReadProjects, session: AsyncSession = Depends(get_session)
) -> Response:
    c = await service.get_comment(session, comment_id)
    task = await service.get(session, c.task_id)
    access = await _access(session, user, task.project_id)
    if c.author_user_id != user.id and not access.can_manage:
        raise Forbidden("You can delete only your own comments")
    await session.delete(c)
    await session.commit()
    return Response(status_code=204)


# ---- timeline --------------------------------------------------------------------------------------


@router.get("/projects/{project_id}/timeline", response_model=TimelineOut)
async def timeline(
    project_id: uuid.UUID, user: CurrentUser = ReadProjects, session: AsyncSession = Depends(get_session)
) -> TimelineOut:
    """Tasks, milestones and the deadline for the Gantt view (Section 11.4). Calendar and Gantt read the same rows."""
    access = await _access(session, user, project_id)
    project = await projects.get(session, project_id)
    today = await settings.today(session)
    tasks = list((await session.execute(service.list_stmt(project_ids=None, project_id=project_id))).scalars())
    ids = [t.id for t in tasks]
    who = await service.assignees(session, ids)
    deps = await service.dependencies(session, ids)
    logged = await service.hours_logged(session, ids)
    names = await employees.names(session, list({e for es in who.values() for e in es}))
    by_id = {t.id: t for t in tasks}
    out = []
    for t in sorted(tasks, key=lambda t: (t.start_date or t.due_date or date.max, t.number)):
        if t.status == "done":
            progress = Decimal(100)
        elif t.estimate_hours:
            progress = min(Decimal(95), (logged.get(t.id, Decimal(0)) * 100 / t.estimate_hours).quantize(Decimal(1)))
        else:
            progress = Decimal(0)
        # Delayed: past due and not done, or it ends after a task waiting on it is meant to start.
        waiting = [w for w in tasks if t.id in deps.get(w.id, [])]
        delayed = t.status != "done" and (
            bool(t.due_date and t.due_date < today)
            or any(t.due_date and w.start_date and t.due_date >= w.start_date for w in waiting)
        )
        out.append(
            TimelineTask(
                id=t.id,
                number=t.number,
                title=t.title,
                status=t.status,
                priority=t.priority,
                parent_task_id=t.parent_task_id,
                milestone_id=t.milestone_id,
                start_date=t.start_date,
                due_date=t.due_date,
                progress=progress,
                assignees=[Ref(id=e, name=names.get(e, "?")) for e in who.get(t.id, [])],
                depends_on=[d for d in deps.get(t.id, []) if d in by_id],
                delayed=delayed,
                version=t.version,
            )
        )
    return TimelineOut(
        project_id=project.id,
        project_name=project.name,
        start_date=project.start_date,
        deadline=project.deadline,
        today=today,
        tasks=out,
        milestones=[
            TimelineMilestone(id=m.id, name=m.name, due_date=m.due_date, status=m.status)
            for m in await projects.milestones(session, project_id)
        ],
        can_edit=access.can_manage,
    )
