"""Tasks, subtasks, dependencies, Kanban order, time entries and comments (docs/architecture.md, Section 11.2)."""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.core.numbering import next_number
from app.modules.audit import api as audit
from app.modules.categories import api as categories
from app.modules.employees import api as employees
from app.modules.projects import api as projects
from app.modules.tasks import rank
from app.modules.tasks.models import Task, TaskAssignee, TaskComment, TaskDependency, TimeEntry

FIELDS = (
    "title",
    "description",
    "status",
    "priority",
    "start_date",
    "due_date",
    "estimate_hours",
    "milestone_id",
    "parent_task_id",
    "task_category_id",
    "task_category_other_text",
)
ZERO = Decimal(0)


def _snapshot(t: Task) -> dict[str, Any]:
    return {k: getattr(t, k) for k in FIELDS}


async def get(session: AsyncSession, task_id: uuid.UUID, *, lock: bool = False) -> Task:
    stmt = select(Task).where(Task.id == task_id)
    if lock:
        stmt = stmt.with_for_update()
    task = (await session.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise NotFound("Task not found")
    return task


def list_stmt(
    *,
    project_ids: set[uuid.UUID] | None,
    project_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
    status: list[str] | None = None,
    milestone_id: uuid.UUID | None = None,
    parent_task_id: uuid.UUID | None = None,
    top_level: bool = False,
    q: str | None = None,
    due_before: date | None = None,
) -> Select[tuple[Task]]:
    stmt = select(Task).order_by(Task.status, Task.board_rank)
    if project_ids is not None:
        stmt = stmt.where(Task.project_id.in_(project_ids))
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if assignee_id:
        stmt = stmt.where(Task.id.in_(select(TaskAssignee.task_id).where(TaskAssignee.employee_id == assignee_id)))
    if status:
        stmt = stmt.where(Task.status.in_(status))
    if milestone_id:
        stmt = stmt.where(Task.milestone_id == milestone_id)
    if parent_task_id:
        stmt = stmt.where(Task.parent_task_id == parent_task_id)
    if top_level:
        stmt = stmt.where(Task.parent_task_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Task.title.ilike(like) | Task.number.ilike(like))
    if due_before:
        stmt = stmt.where(Task.due_date <= due_before)
    return stmt


# ---- related rows ----------------------------------------------------------------------------------


async def assignees(session: AsyncSession, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    if task_ids:
        for t, e in (
            await session.execute(
                select(TaskAssignee.task_id, TaskAssignee.employee_id).where(TaskAssignee.task_id.in_(task_ids))
            )
        ).all():
            out[t].append(e)
    return out


async def dependencies(session: AsyncSession, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    if task_ids:
        for t, d in (
            await session.execute(
                select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(
                    TaskDependency.task_id.in_(task_ids)
                )
            )
        ).all():
            out[t].append(d)
    return out


async def hours_logged(session: AsyncSession, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not task_ids:
        return {}
    rows = await session.execute(
        select(TimeEntry.task_id, func.sum(TimeEntry.hours))
        .where(TimeEntry.task_id.in_(task_ids))
        .group_by(TimeEntry.task_id)
    )
    return dict(rows.all())  # type: ignore[arg-type]


async def hours_by_employee(session: AsyncSession, *, date_from: date, date_to: date) -> dict[uuid.UUID, Decimal]:
    """Hours logged per employee on work dates in the range (all tasks)."""
    rows = await session.execute(
        select(TimeEntry.employee_id, func.sum(TimeEntry.hours))
        .where(TimeEntry.work_date.between(date_from, date_to))
        .group_by(TimeEntry.employee_id)
    )
    return dict(rows.all())  # type: ignore[arg-type]


async def subtask_counts(session: AsyncSession, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    """(subtasks, done subtasks) per parent."""
    if not task_ids:
        return {}
    rows = await session.execute(
        select(Task.parent_task_id, func.count(), func.count().filter(Task.status == "done"))
        .where(Task.parent_task_id.in_(task_ids))
        .group_by(Task.parent_task_id)
    )
    return {p: (n, d) for p, n, d in rows.all()}


async def is_assignee(session: AsyncSession, task_id: uuid.UUID, employee_id: uuid.UUID) -> bool:
    return (
        await session.execute(
            select(TaskAssignee).where(TaskAssignee.task_id == task_id, TaskAssignee.employee_id == employee_id)
        )
    ).first() is not None


# ---- validation ------------------------------------------------------------------------------------


async def _validate(session: AsyncSession, task: Task) -> None:
    errors = []
    if task.milestone_id:
        try:
            m = await projects.get_milestone(session, task.milestone_id)
            if m.project_id != task.project_id:
                errors.append(field_error("milestone_id", "That milestone belongs to another project"))
        except NotFound:
            errors.append(field_error("milestone_id", "Unknown milestone"))
    if task.parent_task_id:
        try:
            parent = await get(session, task.parent_task_id)
        except NotFound:
            errors.append(field_error("parent_task_id", "Unknown task"))
        else:
            if parent.project_id != task.project_id:
                errors.append(field_error("parent_task_id", "The parent task belongs to another project"))
            # Walk up: the new parent may not be this task or one of its subtasks.
            seen, cur = set(), parent
            while cur is not None and task.id is not None:
                if cur.id == task.id:
                    errors.append(field_error("parent_task_id", "A task can't be under its own subtask"))
                    break
                if cur.id in seen or cur.parent_task_id is None:
                    break
                seen.add(cur.id)
                cur = await session.get(Task, cur.parent_task_id)
    if task.task_category_id:
        await categories.validate_choice(
            session,
            group_key="task_category",
            category_id=task.task_category_id,
            other_text=task.task_category_other_text,
            field="task_category_id",
            other_field="task_category_other_text",
        )
    if task.start_date and task.due_date and task.due_date < task.start_date:
        errors.append(field_error("due_date", "Must be on or after the start date"))
    if errors:
        raise ValidationFailed("Invalid task", errors=errors)


async def _last_rank(session: AsyncSession, project_id: uuid.UUID, status: str) -> str | None:
    return (
        await session.execute(
            select(func.max(Task.board_rank)).where(Task.project_id == project_id, Task.status == status)
        )
    ).scalar_one()


async def _set_assignees(session: AsyncSession, task: Task, employee_ids: list[uuid.UUID]) -> None:
    ids = list(dict.fromkeys(employee_ids))
    for i, eid in enumerate(ids):
        try:
            await employees.get(session, eid)
        except NotFound:
            raise ValidationFailed("Unknown employee", errors=[field_error(f"assignee_ids.{i}", "Not found")]) from None
    await session.execute(delete(TaskAssignee).where(TaskAssignee.task_id == task.id))
    session.add_all(TaskAssignee(task_id=task.id, employee_id=e) for e in ids)
    await session.flush()


def _done_stamp(task: Task) -> None:
    if task.status == "done" and task.completed_at is None:
        task.completed_at = datetime.now(UTC)
    elif task.status != "done":
        task.completed_at = None


# ---- create / update / delete ----------------------------------------------------------------------


async def create(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    project_id: uuid.UUID,
    data: dict[str, Any],
    assignee_ids: list[uuid.UUID] | None = None,
) -> Task:
    await projects.get(session, project_id)
    task = Task(
        number=await next_number(session, "TSK", None),
        project_id=project_id,
        created_by=actor_id,
        updated_by=actor_id,
        **{k: v for k, v in data.items() if k in FIELDS},
    )
    task.status = task.status or "todo"
    task.priority = task.priority or "medium"
    await _validate(session, task)
    task.board_rank = rank.between(await _last_rank(session, project_id, task.status), None)
    _done_stamp(task)
    session.add(task)
    await session.flush()
    if assignee_ids:
        await _set_assignees(session, task, assignee_ids)
    await audit.record(
        session,
        actor_id=actor_id,
        action="task.created",
        entity_type="task",
        entity_id=task.id,
        after={"number": task.number, **_snapshot(task)},
    )
    return task


async def update(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    task_id: uuid.UUID,
    version: int,
    changes: dict[str, Any],
    assignee_ids: list[uuid.UUID] | None = None,
) -> Task:
    task = await get(session, task_id, lock=True)
    if task.version != version:
        raise PreconditionFailed()
    before = _snapshot(task)
    old_status = task.status
    for k, v in changes.items():
        if k in FIELDS:
            setattr(task, k, v)
    await _validate(session, task)
    if task.status != old_status:  # changed column: go to the end of the new one
        task.board_rank = rank.between(await _last_rank(session, task.project_id, task.status), None)
    _done_stamp(task)
    task.version += 1
    task.updated_by = actor_id
    await session.flush()
    if assignee_ids is not None:
        await _set_assignees(session, task, assignee_ids)
    b, a = audit.diff(before, _snapshot(task))
    if a:
        await audit.record(
            session, actor_id=actor_id, action="task.updated", entity_type="task", entity_id=task.id, before=b, after=a
        )
    return task


async def move(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    task_id: uuid.UUID,
    version: int,
    status: str,
    before_id: uuid.UUID | None,
    after_id: uuid.UUID | None,
) -> Task:
    """Kanban drag: into `status`, between the card above (`before_id`) and the card below (`after_id`)."""
    task = await get(session, task_id, lock=True)
    if task.version != version:
        raise PreconditionFailed()

    async def neighbour(nid: uuid.UUID | None) -> str | None:
        if nid is None:
            return None
        n = await get(session, nid)
        if n.project_id != task.project_id or n.status != status or n.id == task.id:
            raise ValidationFailed(
                "Invalid position", errors=[field_error("position", "Neighbour is not in that column")]
            )
        return n.board_rank

    lo, hi = await neighbour(before_id), await neighbour(after_id)
    if before_id is None and after_id is None:  # no position given: end of the column
        lo = await _last_rank(session, task.project_id, status)
    if lo is not None and hi is not None and lo >= hi:
        raise Conflict("The board changed; reload and try again")
    old_status = task.status
    task.board_rank = rank.between(lo, hi)
    task.status = status
    _done_stamp(task)
    task.version += 1
    task.updated_by = actor_id
    await session.flush()
    if old_status != status:
        await audit.record(
            session,
            actor_id=actor_id,
            action="task.updated",
            entity_type="task",
            entity_id=task.id,
            before={"status": old_status},
            after={"status": status},
        )
    return task


async def delete_task(session: AsyncSession, *, actor_id: uuid.UUID, task_id: uuid.UUID) -> None:
    task = await get(session, task_id, lock=True)
    ids = await _subtree(session, task.id)
    logged = (
        await session.execute(select(func.count()).select_from(TimeEntry).where(TimeEntry.task_id.in_(ids)))
    ).scalar_one()
    if logged:
        raise Conflict("Time has been logged on this task or its subtasks; mark it done or cancel instead of deleting")
    number = task.number
    await session.delete(task)  # subtasks, assignees, dependencies and comments go with it
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="task.deleted",
        entity_type="task",
        entity_id=task_id,
        before={"number": number},
    )


async def _subtree(session: AsyncSession, root: uuid.UUID) -> list[uuid.UUID]:
    out, frontier = [root], [root]
    while frontier:
        frontier = list((await session.execute(select(Task.id).where(Task.parent_task_id.in_(frontier)))).scalars())
        out += frontier
    return out


# ---- dependencies ----------------------------------------------------------------------------------


async def add_dependency(
    session: AsyncSession, *, actor_id: uuid.UUID, task_id: uuid.UUID, depends_on_id: uuid.UUID
) -> None:
    task, other = await get(session, task_id), await get(session, depends_on_id)
    if task.id == other.id:
        raise ValidationFailed(
            "Invalid dependency", errors=[field_error("depends_on_task_id", "A task can't depend on itself")]
        )
    if task.project_id != other.project_id:
        raise ValidationFailed(
            "Invalid dependency", errors=[field_error("depends_on_task_id", "Both tasks must be in the same project")]
        )
    # Cycle check: would `other` (transitively) wait for `task`?
    frontier, seen = [other.id], set()
    while frontier:
        if task.id in frontier:
            raise ValidationFailed(
                "Circular dependency",
                errors=[field_error("depends_on_task_id", f"{other.number} already waits for {task.number}", "cycle")],
            )
        seen.update(frontier)
        frontier = [
            d
            for d in (
                await session.execute(
                    select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id.in_(frontier))
                )
            ).scalars()
            if d not in seen
        ]
    exists = await session.get(TaskDependency, (task.id, other.id))
    if exists:
        return
    session.add(TaskDependency(task_id=task.id, depends_on_task_id=other.id))
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="task.dependency_added",
        entity_type="task",
        entity_id=task.id,
        after={"depends_on": other.number},
    )


async def remove_dependency(
    session: AsyncSession, *, actor_id: uuid.UUID, task_id: uuid.UUID, depends_on_id: uuid.UUID
) -> None:
    await session.execute(
        delete(TaskDependency).where(
            TaskDependency.task_id == task_id, TaskDependency.depends_on_task_id == depends_on_id
        )
    )
    await audit.record(
        session,
        actor_id=actor_id,
        action="task.dependency_removed",
        entity_type="task",
        entity_id=task_id,
        before={"depends_on_task_id": depends_on_id},
    )


# ---- time entries ----------------------------------------------------------------------------------


async def time_entries(session: AsyncSession, task_id: uuid.UUID) -> list[TimeEntry]:
    return list(
        (
            await session.execute(
                select(TimeEntry)
                .where(TimeEntry.task_id == task_id)
                .order_by(TimeEntry.work_date.desc(), TimeEntry.created_at.desc())
            )
        ).scalars()
    )


async def log_time(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    task_id: uuid.UUID,
    employee_id: uuid.UUID,
    work_date: date,
    hours: Decimal,
    note: str | None,
) -> TimeEntry:
    await get(session, task_id)
    await employees.get(session, employee_id)
    day_total = (
        await session.execute(
            select(func.coalesce(func.sum(TimeEntry.hours), 0)).where(
                TimeEntry.employee_id == employee_id, TimeEntry.work_date == work_date
            )
        )
    ).scalar_one()
    if day_total + hours > 24:
        raise ValidationFailed(
            "Too many hours", errors=[field_error("hours", f"Already {day_total} h logged that day")]
        )
    entry = TimeEntry(
        task_id=task_id, employee_id=employee_id, work_date=work_date, hours=hours, note=note, created_by=actor_id
    )
    session.add(entry)
    await session.flush()
    return entry


async def get_time_entry(session: AsyncSession, entry_id: uuid.UUID) -> TimeEntry:
    e = await session.get(TimeEntry, entry_id)
    if e is None:
        raise NotFound("Time entry not found")
    return e


async def delete_time_entry(session: AsyncSession, *, entry_id: uuid.UUID) -> None:
    await session.delete(await get_time_entry(session, entry_id))
    await session.flush()


# ---- comments --------------------------------------------------------------------------------------


async def comments(session: AsyncSession, task_id: uuid.UUID) -> list[TaskComment]:
    return list(
        (
            await session.execute(
                select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.created_at)
            )
        ).scalars()
    )


async def add_comment(session: AsyncSession, *, author_id: uuid.UUID, task_id: uuid.UUID, body: str) -> TaskComment:
    await get(session, task_id)
    if not body.strip():
        raise ValidationFailed("Empty comment", errors=[field_error("body", "Write something")])
    c = TaskComment(task_id=task_id, author_user_id=author_id, body=body.strip())
    session.add(c)
    await session.flush()
    return c


async def get_comment(session: AsyncSession, comment_id: uuid.UUID) -> TaskComment:
    c = await session.get(TaskComment, comment_id)
    if c is None:
        raise NotFound("Comment not found")
    return c


# ---- progress --------------------------------------------------------------------------------------


@dataclass
class Progress:
    total: int
    done: int
    percent: Decimal  # estimate-weighted share done (tasks without an estimate count as 1 hour)
    estimate_hours: Decimal
    logged_hours: Decimal
    overdue: int


@dataclass
class Activity:
    created: int = 0
    completed: int = 0
    open: int = 0
    overdue: int = 0
    last_activity: datetime | None = None


async def activity(
    session: AsyncSession, project_ids: list[uuid.UUID], *, date_from: date, date_to: date, today: date
) -> dict[uuid.UUID, Activity]:
    """Per project: tasks created and completed in the date range, tasks open and overdue now, and when anyone
    last touched a task, comment or time entry."""
    out: dict[uuid.UUID, Activity] = {}
    if not project_ids:
        return out

    def touched(pid: uuid.UUID, when: datetime | None) -> None:
        a = out.setdefault(pid, Activity())
        if when and (a.last_activity is None or when > a.last_activity):
            a.last_activity = when

    rows = await session.execute(
        select(Task.project_id, Task.status, Task.due_date, Task.created_at, Task.completed_at, Task.updated_at).where(
            Task.project_id.in_(project_ids)
        )
    )
    for pid, status, due, created, completed, updated in rows.all():
        touched(pid, updated)
        a = out[pid]
        a.created += date_from <= created.date() <= date_to
        a.completed += bool(completed and date_from <= completed.date() <= date_to)
        if status != "done":
            a.open += 1
            a.overdue += bool(due and due < today)
    for table in (TaskComment, TimeEntry):
        latest = await session.execute(
            select(Task.project_id, func.max(table.created_at))
            .join(Task, Task.id == table.task_id)
            .where(Task.project_id.in_(project_ids))
            .group_by(Task.project_id)
        )
        for pid, when in latest.all():
            touched(pid, when)
    return out


async def progress(session: AsyncSession, project_ids: list[uuid.UUID], today: date) -> dict[uuid.UUID, Progress]:
    out: dict[uuid.UUID, Progress] = {}
    if not project_ids:
        return out
    rows = (
        await session.execute(
            select(Task.project_id, Task.status, Task.estimate_hours, Task.due_date).where(
                Task.project_id.in_(project_ids)
            )
        )
    ).all()
    weight: dict[uuid.UUID, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
    for pid, status, est, due in rows:
        p = out.setdefault(pid, Progress(0, 0, ZERO, ZERO, ZERO, 0))
        w = est if est else Decimal(1)
        p.total += 1
        p.estimate_hours += est or ZERO
        weight[pid][0] += w
        if status == "done":
            p.done += 1
            weight[pid][1] += w
        elif due and due < today:
            p.overdue += 1
    logged = await session.execute(
        select(Task.project_id, func.sum(TimeEntry.hours))
        .join(Task, Task.id == TimeEntry.task_id)
        .where(Task.project_id.in_(project_ids))
        .group_by(Task.project_id)
    )
    for pid, hours in logged.all():
        out.setdefault(pid, Progress(0, 0, ZERO, ZERO, ZERO, 0)).logged_hours = hours or ZERO
    for pid, (total, done) in weight.items():
        out[pid].percent = (done * 100 / total).quantize(Decimal("0.1")) if total else ZERO
    return out


def blocking_stmt(task_id: uuid.UUID) -> Select[tuple[Task]]:
    """Tasks that wait for `task_id`."""
    return (
        select(Task)
        .where(Task.id.in_(select(TaskDependency.task_id).where(TaskDependency.depends_on_task_id == task_id)))
        .order_by(Task.number)
    )


async def scheduled(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    project_ids: set[uuid.UUID] | None = None,
    assignee_ids: set[uuid.UUID] | None = None,
    open_only: bool = False,
) -> list[tuple[Task, list[uuid.UUID]]]:
    """Tasks whose [start, due] touches the range (a task with only a due date sits on that day), with assignees.
    For the calendar feed and workload; the rows stay the single source of truth."""
    start = func.coalesce(Task.start_date, Task.due_date)
    stmt = select(Task).where(Task.due_date.is_not(None), start <= date_to, Task.due_date >= date_from)
    if project_ids is not None:
        stmt = stmt.where(Task.project_id.in_(project_ids))
    if assignee_ids is not None:
        stmt = stmt.where(Task.id.in_(select(TaskAssignee.task_id).where(TaskAssignee.employee_id.in_(assignee_ids))))
    if open_only:
        stmt = stmt.where(Task.status != "done")
    rows = list((await session.execute(stmt.order_by(Task.due_date))).scalars())
    who = await assignees(session, [t.id for t in rows])
    return [(t, who.get(t.id, [])) for t in rows]


async def counts(
    session: AsyncSession,
    *,
    today: date,
    project_ids: set[uuid.UUID] | None = None,
    assignee_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Open, overdue and due-within-7-days task counts."""
    base = select(func.count()).select_from(Task).where(Task.status != "done")
    if project_ids is not None:
        base = base.where(Task.project_id.in_(project_ids))
    if assignee_id is not None:
        base = base.where(Task.id.in_(select(TaskAssignee.task_id).where(TaskAssignee.employee_id == assignee_id)))
    week = date.fromordinal(today.toordinal() + 7)
    return {
        "open": (await session.execute(base)).scalar_one(),
        "overdue": (await session.execute(base.where(Task.due_date < today))).scalar_one(),
        "due_soon": (await session.execute(base.where(Task.due_date.between(today, week)))).scalar_one(),
    }
