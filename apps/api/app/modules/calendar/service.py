"""Calendar: events, leave, the derived feed, workload and reminders (docs/architecture.md, Section 11.3)."""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.modules.audit import api as audit
from app.modules.auth.api import CurrentUser
from app.modules.calendar import recurrence
from app.modules.calendar.models import CalendarEvent, EventAttendee, EventException, Notification
from app.modules.categories import api as categories
from app.modules.employees import api as employees
from app.modules.projects import api as projects
from app.modules.rbac.api import Scope
from app.modules.settings import api as settings
from app.modules.tasks import api as tasks

FIELDS = (
    "scope",
    "owner_employee_id",
    "department_id",
    "project_id",
    "event_type_category_id",
    "event_type_other_text",
    "title",
    "description",
    "location",
    "all_day",
    "start_at",
    "end_at",
    "start_date",
    "end_date",
    "timezone",
    "rrule",
    "reminders",
)
HOURS_PER_DAY = Decimal(8)
MAX_RANGE_DAYS = 400


# ---- who the user is -------------------------------------------------------------------------------


@dataclass
class Viewer:
    user: CurrentUser
    employee_id: uuid.UUID | None
    department_id: uuid.UUID | None
    project_ids: set[uuid.UUID] | None  # None = all projects visible

    def can(self, permission: str, scope: Scope = Scope.OWN) -> bool:
        return self.user.can(permission, scope)


async def viewer(session: AsyncSession, user: CurrentUser) -> Viewer:
    own = await employees.for_user(session, user.id)
    visible = (
        None if user.scope_for("projects.read") == Scope.ALL else await projects.visible_project_ids(session, user)
    )
    return Viewer(user, own.id if own else None, own.department_id if own else None, visible)


async def _event_type(session: AsyncSession, category_id: uuid.UUID | None) -> Any:
    return await categories.get(session, category_id) if category_id else None


async def is_leave(session: AsyncSession, event: CalendarEvent) -> bool:
    t = await _event_type(session, event.event_type_category_id)
    return bool(t and t.config.get("counts_as_unavailable"))


def _can_manage_scope(v: Viewer, event: CalendarEvent) -> bool:
    """May create or change an event of this scope."""
    if v.can("calendar.manage.company", Scope.ALL):
        return True  # administrators / HR
    if event.scope == "personal":
        return event.owner_employee_id is not None and event.owner_employee_id == v.employee_id
    if event.scope == "team":
        scope = v.user.scope_for("calendar.manage.team")
        return scope == Scope.ALL or (scope is not None and event.department_id == v.department_id)
    if event.scope == "project":
        scope = v.user.scope_for("tasks.manage")
        member = v.project_ids is None or event.project_id in v.project_ids
        return scope == Scope.ALL or (scope is not None and member and event.project_id is not None)
    return False  # company


async def can_see(session: AsyncSession, v: Viewer, event: CalendarEvent, attendees: list[uuid.UUID]) -> bool:
    if event.scope == "company":
        return True
    if event.scope == "team":
        return v.can("employees.read", Scope.ALL) or event.department_id == v.department_id
    if event.scope == "project":
        return v.project_ids is None or event.project_id in v.project_ids
    # personal: owner, attendees, managers; everyone sees leave (who is away is not private)
    if v.employee_id and (event.owner_employee_id == v.employee_id or v.employee_id in attendees):
        return True
    return v.can("calendar.manage.company", Scope.ALL) or v.can("leave.approve") or await is_leave(session, event)


# ---- events ----------------------------------------------------------------------------------------


async def get(session: AsyncSession, event_id: uuid.UUID) -> CalendarEvent:
    e = await session.get(CalendarEvent, event_id)
    if e is None:
        raise NotFound("Event not found")
    return e


async def attendees_of(
    session: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[uuid.UUID, str]]]:
    out: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = defaultdict(list)
    if event_ids:
        rows = await session.execute(
            select(EventAttendee.event_id, EventAttendee.employee_id, EventAttendee.response).where(
                EventAttendee.event_id.in_(event_ids)
            )
        )
        for e, emp, resp in rows.all():
            out[e].append((emp, resp))
    return out


async def _validate(session: AsyncSession, e: CalendarEvent) -> None:
    errors = []
    try:
        recurrence.zone(e.timezone)
    except recurrence.RecurrenceError:
        errors.append(field_error("timezone", "Unknown time zone"))
    if e.all_day:
        if not e.start_date or not e.end_date:
            errors.append(field_error("start_date", "All-day events need start and end dates", "required"))
        elif e.end_date < e.start_date:
            errors.append(field_error("end_date", "Must be on or after the start"))
        e.start_at = e.end_at = None
    else:
        if not e.start_at or not e.end_at:
            errors.append(field_error("start_at", "Timed events need a start and end time", "required"))
        elif e.end_at < e.start_at:
            errors.append(field_error("end_at", "Must be after the start"))
        e.start_date = e.end_date = None
    if e.scope == "project" and not e.project_id:
        errors.append(field_error("project_id", "Choose the project", "required"))
    if e.scope == "team" and not e.department_id:
        errors.append(field_error("department_id", "Choose the team (department)", "required"))
    if e.scope == "personal" and not e.owner_employee_id:
        errors.append(field_error("owner_employee_id", "Whose calendar?", "required"))
    if e.event_type_category_id:
        await categories.validate_choice(
            session,
            group_key="event_type",
            category_id=e.event_type_category_id,
            other_text=e.event_type_other_text,
            field="event_type_category_id",
            other_field="event_type_other_text",
        )
    if any(not isinstance(m, int) or m < 0 or m > 40320 for m in e.reminders or []):
        errors.append(field_error("reminders", "Minutes before, between 0 and 40320 (4 weeks)"))
    try:
        e.rrule = recurrence.normalize(e.rrule, tz=e.timezone, all_day=e.all_day)
    except recurrence.RecurrenceError as exc:
        errors.append(field_error("rrule", str(exc)))
    if errors:
        raise ValidationFailed("Invalid event", errors=errors)


async def _set_attendees(session: AsyncSession, e: CalendarEvent, ids: list[uuid.UUID]) -> None:
    ids = list(dict.fromkeys(ids))
    found = {x.id for x in await employees.by_ids(session, ids)}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValidationFailed("Unknown attendee", errors=[field_error("attendee_ids", "Not found")])
    existing = {emp: resp for emp, resp in (await attendees_of(session, [e.id])).get(e.id, [])}
    await session.execute(delete(EventAttendee).where(EventAttendee.event_id == e.id))
    session.add_all(EventAttendee(event_id=e.id, employee_id=i, response=existing.get(i, "needs_action")) for i in ids)
    await session.flush()


def _snapshot(e: CalendarEvent) -> dict[str, Any]:
    return {k: getattr(e, k) for k in (*FIELDS, "status")}


async def create(
    session: AsyncSession, *, v: Viewer, data: dict[str, Any], attendee_ids: list[uuid.UUID]
) -> CalendarEvent:
    e = CalendarEvent(created_by=v.user.id, updated_by=v.user.id, **{k: data.get(k) for k in FIELDS if k in data})
    e.reminders = e.reminders or []
    if e.scope == "personal" and not e.owner_employee_id:
        e.owner_employee_id = v.employee_id
    if not _can_manage_scope(v, e):
        raise Forbidden("You can't add events to that calendar")
    await _validate(session, e)
    if await is_leave(session, e):
        # Leave needs approval unless the requester approves leave for everyone.
        e.status = "approved" if v.can("leave.approve", Scope.ALL) else "requested"
        if e.status == "approved":
            e.decided_by, e.decided_at = v.user.id, datetime.now(UTC)
    session.add(e)
    await session.flush()
    await _set_attendees(session, e, attendee_ids)
    await audit.record(
        session,
        actor_id=v.user.id,
        action="calendar_event.created",
        entity_type="calendar_event",
        entity_id=e.id,
        after=_snapshot(e),
    )
    return e


async def update(
    session: AsyncSession,
    *,
    v: Viewer,
    event_id: uuid.UUID,
    version: int,
    changes: dict[str, Any],
    attendee_ids: list[uuid.UUID] | None,
) -> CalendarEvent:
    e = await get(session, event_id)
    if e.version != version:
        raise PreconditionFailed()
    if not _can_manage_scope(v, e) and e.created_by != v.user.id:
        raise Forbidden("You can't change this event")
    before = _snapshot(e)
    for k, val in changes.items():
        if k in FIELDS:
            setattr(e, k, val)
    if not _can_manage_scope(v, e):
        raise Forbidden("You can't move the event to that calendar")
    await _validate(session, e)
    # Changing approved leave sends it back for approval.
    moved = any(before[k] != getattr(e, k) for k in ("start_date", "end_date", "start_at", "end_at", "rrule"))
    if moved and e.status == "approved" and not v.can("leave.approve", Scope.ALL) and await is_leave(session, e):
        e.status = "requested"
        e.decided_by = e.decided_at = None
    e.version += 1
    e.updated_by = v.user.id
    await session.flush()
    if attendee_ids is not None:
        await _set_attendees(session, e, attendee_ids)
    b, a = audit.diff(before, _snapshot(e))
    if a:
        await audit.record(
            session,
            actor_id=v.user.id,
            action="calendar_event.updated",
            entity_type="calendar_event",
            entity_id=e.id,
            before=b,
            after=a,
        )
    return e


async def delete_event(session: AsyncSession, *, v: Viewer, event_id: uuid.UUID) -> None:
    e = await get(session, event_id)
    if not _can_manage_scope(v, e) and e.created_by != v.user.id:
        raise Forbidden("You can't delete this event")
    title = e.title
    await session.delete(e)
    await session.flush()
    await audit.record(
        session,
        actor_id=v.user.id,
        action="calendar_event.deleted",
        entity_type="calendar_event",
        entity_id=event_id,
        before={"title": title},
    )


async def cancel_occurrence(session: AsyncSession, *, v: Viewer, event_id: uuid.UUID, occurrence: str) -> None:
    e = await get(session, event_id)
    if not _can_manage_scope(v, e) and e.created_by != v.user.id:
        raise Forbidden("You can't change this event")
    if not e.rrule:
        raise Conflict("This event doesn't repeat; delete it instead")
    await session.execute(insert(EventException).values(event_id=e.id, occurrence=occurrence).on_conflict_do_nothing())


async def respond(session: AsyncSession, *, v: Viewer, event_id: uuid.UUID, response: str) -> None:
    if v.employee_id is None:
        raise Forbidden("Your user isn't linked to an employee")
    row = await session.get(EventAttendee, (event_id, v.employee_id))
    if row is None:
        raise NotFound("You're not invited to this event")
    row.response = response
    await session.flush()


async def decide_leave(
    session: AsyncSession, *, v: Viewer, event_id: uuid.UUID, approve: bool, note: str | None
) -> CalendarEvent:
    e = await get(session, event_id)
    if not await is_leave(session, e):
        raise Conflict("Only leave needs approval")
    if e.status not in ("requested", "approved", "rejected"):
        raise Conflict(f"Leave is {e.status}")
    scope = v.user.scope_for("leave.approve")
    allowed = scope == Scope.ALL
    if scope is not None and not allowed and e.owner_employee_id:
        team = await projects.team_ids(session, v.project_ids or set())
        allowed = e.owner_employee_id in team and e.owner_employee_id != v.employee_id
    if not allowed:
        raise Forbidden("You can't approve this leave")
    e.status = "approved" if approve else "rejected"
    e.decided_by, e.decided_at, e.decision_note = v.user.id, datetime.now(UTC), note
    e.version += 1
    await session.flush()
    await audit.record(
        session,
        actor_id=v.user.id,
        action=f"leave.{e.status}",
        entity_type="calendar_event",
        entity_id=e.id,
        after={"title": e.title, "note": note},
    )
    owner = (await employees.by_ids(session, [e.owner_employee_id]))[0] if e.owner_employee_id else None
    if owner and owner.user_id:
        await notify(
            session,
            user_id=owner.user_id,
            kind=f"leave_{e.status}",
            title=f"Leave {e.status}: {e.title}",
            body=note,
            link="/calendar/me",
            dedupe_key=f"leave:{e.id}:{e.version}",
        )
    return e


async def pending_leave(session: AsyncSession, v: Viewer) -> list[CalendarEvent]:
    """Leave requests this user may decide on."""
    scope = v.user.scope_for("leave.approve")
    if scope is None:
        return []
    rows = list(
        (
            await session.execute(
                select(CalendarEvent).where(CalendarEvent.status == "requested").order_by(CalendarEvent.start_date)
            )
        ).scalars()
    )
    if scope == Scope.ALL:
        return rows
    team = await projects.team_ids(session, v.project_ids or set())
    return [e for e in rows if e.owner_employee_id in team and e.owner_employee_id != v.employee_id]


# ---- feed ------------------------------------------------------------------------------------------


@dataclass
class Item:
    key: str
    kind: str  # event | leave | task | milestone | deadline
    title: str
    all_day: bool
    start: str  # ISO date (all-day) or ISO UTC datetime
    end: str
    color: str
    id: uuid.UUID
    occurrence: str | None = None
    status: str | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    employee_ids: list[uuid.UUID] = field(default_factory=list)
    scope: str | None = None
    location: str | None = None
    recurring: bool = False
    editable: bool = False
    link: str | None = None


def _bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    if (date_to - date_from).days > MAX_RANGE_DAYS:
        raise ValidationFailed("Range too long", errors=[field_error("to", f"At most {MAX_RANGE_DAYS} days")])
    return datetime.combine(date_from, time(), UTC) - timedelta(days=1), datetime.combine(
        date_to + timedelta(days=1), time(), UTC
    ) + timedelta(days=1)


async def _events_for(
    session: AsyncSession,
    *,
    date_from: date,
    date_to: date,
    employee_ids: set[uuid.UUID] | None,
    department_ids: set[uuid.UUID],
    project_ids: set[uuid.UUID] | None,
    company: bool,
) -> list[CalendarEvent]:
    """Events that may fall in the range (recurring ones are filtered after expansion)."""
    lo, hi = _bounds(date_from, date_to)
    in_range = or_(
        CalendarEvent.rrule.is_not(None),
        CalendarEvent.start_date <= date_to,
        CalendarEvent.start_at < hi,
    )
    not_ended = or_(
        CalendarEvent.rrule.is_not(None),
        CalendarEvent.end_date >= date_from,
        CalendarEvent.end_at > lo,
    )
    who = []
    if company:
        who.append(CalendarEvent.scope == "company")
    if department_ids:
        who.append((CalendarEvent.scope == "team") & CalendarEvent.department_id.in_(department_ids))
    if project_ids is None:
        who.append(CalendarEvent.scope == "project")
    elif project_ids:
        who.append((CalendarEvent.scope == "project") & CalendarEvent.project_id.in_(project_ids))
    if employee_ids is None:
        who.append(CalendarEvent.scope == "personal")
    elif employee_ids:
        who.append(CalendarEvent.owner_employee_id.in_(employee_ids))
        who.append(
            CalendarEvent.id.in_(select(EventAttendee.event_id).where(EventAttendee.employee_id.in_(employee_ids)))
        )
    if not who:
        return []
    stmt = select(CalendarEvent).where(
        in_range, not_ended, CalendarEvent.status.notin_(("cancelled", "rejected")), or_(*who)
    )
    return list((await session.execute(stmt)).scalars())


async def _exceptions(session: AsyncSession, ids: list[uuid.UUID]) -> set[tuple[uuid.UUID, str]]:
    if not ids:
        return set()
    rows = await session.execute(
        select(EventException.event_id, EventException.occurrence).where(EventException.event_id.in_(ids))
    )
    return {(e, o) for e, o in rows.all()}


def expand(e: CalendarEvent, date_from: date, date_to: date) -> list[recurrence.Occurrence]:
    if e.all_day:
        return recurrence.expand_all_day(e.start_date, e.end_date, e.rrule, date_from, date_to)  # type: ignore[arg-type]
    lo, hi = _bounds(date_from, date_to)
    return recurrence.expand_timed(e.start_at, e.end_at, e.timezone, e.rrule, lo, hi)  # type: ignore[arg-type]


async def feed(
    session: AsyncSession,
    v: Viewer,
    *,
    date_from: date,
    date_to: date,
    view: str,
    department_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> list[Item]:
    """`view`: me (my calendar), team (a department or a project team), company."""
    employee_ids: set[uuid.UUID] | None
    department_ids: set[uuid.UUID] = set()
    project_ids: set[uuid.UUID] | None
    company = False
    task_assignees: set[uuid.UUID] | None = None
    task_projects: set[uuid.UUID] | None
    if view == "me":
        employee_ids = {v.employee_id} if v.employee_id else set()
        department_ids = {v.department_id} if v.department_id else set()
        project_ids = (
            v.project_ids if v.project_ids is not None else await projects.visible_project_ids(session, v.user)
        )
        company = True
        task_assignees = employee_ids
        task_projects = None
    elif view == "team":
        if project_id:
            project = await projects.get(session, project_id)
            await projects.ensure_visible(session, v.user, "projects.read", project)
            employee_ids = await projects.team_ids(session, {project_id})
            project_ids = {project_id}
            task_projects = {project_id}
        else:
            dept = department_id or v.department_id
            if dept is None:
                raise ValidationFailed(
                    "Choose a team", errors=[field_error("department_id", "Choose a team", "required")]
                )
            if dept != v.department_id and not v.can("employees.read", Scope.ALL):
                raise Forbidden("You can only see your own team's calendar")
            employee_ids = {e.id for e in await employees.active_in(session, department_id=dept)}
            department_ids = {dept}
            project_ids = set()
            task_projects = v.project_ids
        task_assignees = employee_ids
    else:  # company
        employee_ids = None  # only leave of everyone is shown, see below
        project_ids = v.project_ids
        company = True
        task_projects = None

    items: list[Item] = []
    rows = await _events_for(
        session,
        date_from=date_from,
        date_to=date_to,
        employee_ids=employee_ids,
        department_ids=department_ids,
        project_ids=project_ids if view != "company" else set(),
        company=company,
    )
    att = await attendees_of(session, [e.id for e in rows])
    skipped = await _exceptions(session, [e.id for e in rows if e.rrule])
    types = {c.id: c for c in await categories_for(session, {e.event_type_category_id for e in rows})}
    pnames = await projects.names(session, list({e.project_id for e in rows if e.project_id}))
    for e in rows:
        t = types.get(e.event_type_category_id) if e.event_type_category_id else None
        leave = bool(t and t.config.get("counts_as_unavailable"))
        if view == "company" and e.scope == "personal" and not (leave and e.status == "approved"):
            continue
        attendees = [emp for emp, _ in att.get(e.id, [])]
        if not await can_see(session, v, e, attendees):
            continue
        people = [x for x in [e.owner_employee_id, *attendees] if x]
        for occ in expand(e, date_from, date_to):
            if (e.id, occ.key) in skipped:
                continue
            items.append(
                Item(
                    key=f"event:{e.id}:{occ.key}",
                    kind="leave" if leave else "event",
                    title=e.title,
                    all_day=e.all_day,
                    start=(occ.start_date.isoformat() if e.all_day else occ.start_at.isoformat()),  # type: ignore[union-attr]
                    end=(occ.end_date.isoformat() if e.all_day else occ.end_at.isoformat()),  # type: ignore[union-attr]
                    color=(t.config.get("color") if t else None) or ("amber" if leave else "blue"),
                    id=e.id,
                    occurrence=occ.key if e.rrule else None,
                    status=e.status,
                    project_id=e.project_id,
                    project_name=pnames.get(e.project_id) if e.project_id else None,
                    employee_ids=people,
                    scope=e.scope,
                    location=e.location,
                    recurring=bool(e.rrule),
                    editable=_can_manage_scope(v, e) or e.created_by == v.user.id,
                )
            )

    # Derived items: never copied, so a task date change shows up at once (Section 11.3).
    if view != "company":
        visible = v.project_ids
        scope_projects = task_projects if task_projects is not None else visible
        for task, who in await tasks.scheduled(
            session, date_from=date_from, date_to=date_to, project_ids=scope_projects, assignee_ids=task_assignees
        ):
            if visible is not None and task.project_id not in visible:
                continue
            items.append(
                Item(
                    key=f"task:{task.id}",
                    kind="task",
                    title=f"{task.number} {task.title}",
                    all_day=True,
                    start=(task.start_date or task.due_date).isoformat(),  # type: ignore[union-attr]
                    end=task.due_date.isoformat(),  # type: ignore[union-attr]
                    color="slate",
                    id=task.id,
                    status=task.status,
                    project_id=task.project_id,
                    employee_ids=who,
                    link=f"/projects/{task.project_id}?tab=tasks",
                )
            )
    scope_projects = project_ids if view != "company" else v.project_ids
    if view == "team" and not project_id:
        scope_projects = v.project_ids if v.project_ids is not None else None
    if view != "team" or project_id:
        for m in await projects.milestones_between(session, scope_projects, date_from, date_to):
            items.append(
                Item(
                    key=f"milestone:{m.id}",
                    kind="milestone",
                    title=m.name,
                    all_day=True,
                    start=m.due_date.isoformat(),  # type: ignore[union-attr]
                    end=m.due_date.isoformat(),
                    color="violet",
                    id=m.id,
                    status=m.status,  # type: ignore[union-attr]
                    project_id=m.project_id,
                    link=f"/projects/{m.project_id}?tab=timeline",
                )
            )
        for p in await projects.deadlines_between(session, scope_projects, date_from, date_to):
            items.append(
                Item(
                    key=f"deadline:{p.id}",
                    kind="deadline",
                    title=f"Deadline: {p.name}",
                    all_day=True,
                    start=p.deadline.isoformat(),
                    end=p.deadline.isoformat(),
                    color="red",
                    id=p.id,  # type: ignore[union-attr]
                    project_id=p.id,
                    link=f"/projects/{p.id}",
                )
            )
    task_projects_names = await projects.names(
        session, list({i.project_id for i in items if i.project_id and not i.project_name})
    )
    for i in items:
        if i.project_id and not i.project_name:
            i.project_name = task_projects_names.get(i.project_id)
    items.sort(key=lambda i: (i.start, i.kind))
    return items


async def categories_for(session: AsyncSession, ids: set[uuid.UUID | None]) -> list[Any]:
    out = []
    for cid in {i for i in ids if i}:
        out.append(await categories.get(session, cid))
    return out


# ---- workload --------------------------------------------------------------------------------------


@dataclass
class Day:
    date: date
    capacity: Decimal
    meetings: Decimal = Decimal(0)
    tasks: Decimal = Decimal(0)
    on_leave: bool = False

    @property
    def load(self) -> Decimal:
        return self.meetings + self.tasks


async def workload(
    session: AsyncSession, *, employee_ids: list[uuid.UUID], date_from: date, date_to: date, today: date
) -> dict[uuid.UUID, list[Day]]:
    """Capacity (8 h on weekdays, 0 on approved leave) vs load: meetings + remaining task estimates spread
    evenly over each task's remaining working days, split between assignees (Section 11.3)."""
    if (date_to - date_from).days > 92:
        raise ValidationFailed("Range too long", errors=[field_error("to", "At most 3 months")])
    days = recurrence.days(date_from, date_to)
    out = {emp: [Day(d, HOURS_PER_DAY if d.weekday() < 5 else Decimal(0)) for d in days] for emp in employee_ids}
    index = {d: i for i, d in enumerate(days)}
    ids = set(employee_ids)
    rows = await _events_for(
        session,
        date_from=date_from,
        date_to=date_to,
        employee_ids=ids,
        department_ids=set(),
        project_ids=set(),
        company=False,
    )
    att = await attendees_of(session, [e.id for e in rows])
    skipped = await _exceptions(session, [e.id for e in rows if e.rrule])
    types = {c.id: c for c in await categories_for(session, {e.event_type_category_id for e in rows})}
    for e in rows:
        t = types.get(e.event_type_category_id) if e.event_type_category_id else None
        leave = bool(t and t.config.get("counts_as_unavailable"))
        if leave and e.status != "approved":
            continue
        people = {
            x for x in [e.owner_employee_id, *(emp for emp, r in att.get(e.id, []) if r != "declined")] if x
        } & ids
        for occ in expand(e, date_from, date_to):
            if (e.id, occ.key) in skipped:
                continue
            if e.all_day:
                for d in recurrence.days(occ.start_date, occ.end_date):  # type: ignore[arg-type]
                    if d in index:
                        for emp in people:
                            day = out[emp][index[d]]
                            if leave:
                                day.on_leave, day.capacity = True, Decimal(0)
            elif not leave:
                hours = Decimal((occ.end_at - occ.start_at).total_seconds()) / 3600  # type: ignore[operator]
                d = occ.start_at.date()  # type: ignore[union-attr]
                if d in index:
                    for emp in people:
                        out[emp][index[d]].meetings += hours.quantize(Decimal("0.01"))
    open_tasks = await tasks.scheduled(
        session, date_from=min(date_from, today), date_to=date_to, assignee_ids=ids, open_only=True
    )
    logged = await tasks.hours_logged(session, [t.id for t, _ in open_tasks])
    for task, who in open_tasks:
        remaining = max((task.estimate_hours or Decimal(0)) - logged.get(task.id, Decimal(0)), Decimal(0))
        mine = [w for w in who if w in ids]
        if not remaining or not mine:
            continue
        start = max(task.start_date or task.due_date, today)  # type: ignore[type-var]
        end = max(task.due_date, start)  # type: ignore[type-var]
        working = [d for d in recurrence.days(start, end) if d.weekday() < 5] or [end]
        per_day = remaining / len(working) / len(mine)
        for d in working:
            if d in index:
                for emp in mine:
                    out[emp][index[d]].tasks += per_day.quantize(Decimal("0.01"))
    return out


# ---- notifications ---------------------------------------------------------------------------------


async def notify(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    dedupe_key: str,
    data: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            link=link,
            dedupe_key=dedupe_key,
            data=data or {},
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )


async def send_reminders(session: AsyncSession, now: datetime) -> int:
    """Worker job (every minute): event reminders that are due, and a morning nudge for tasks due today."""
    sent = 0
    horizon = now + timedelta(days=28)
    rows = list(
        (
            await session.execute(
                select(CalendarEvent).where(
                    CalendarEvent.reminders != [], CalendarEvent.status.notin_(("cancelled", "rejected", "requested"))
                )
            )
        ).scalars()
    )
    att = await attendees_of(session, [e.id for e in rows])
    skipped = await _exceptions(session, [e.id for e in rows if e.rrule])
    for e in rows:
        people = {x for x in [e.owner_employee_id, *(emp for emp, r in att.get(e.id, []) if r != "declined")] if x}
        users = [x.user_id for x in await employees.by_ids(session, list(people)) if x.user_id]
        if not users:
            continue
        for occ in expand(e, now.date(), horizon.date()):
            if (e.id, occ.key) in skipped:
                continue
            starts = occ.start_at or datetime.combine(occ.start_date, time(9), recurrence.zone(e.timezone))  # type: ignore[arg-type]
            for minutes in e.reminders:
                due = starts - timedelta(minutes=minutes)
                if due <= now < starts:
                    for u in users:
                        await notify(
                            session,
                            user_id=u,
                            kind="event_reminder",
                            title=f"Reminder: {e.title}",
                            body=f"Starts {starts.astimezone(recurrence.zone(e.timezone)).strftime('%a %d %b %H:%M')}",
                            link="/calendar/me",
                            dedupe_key=f"evt:{e.id}:{occ.key}:{minutes}:{u}",
                        )
                        sent += 1
    today = await settings.today(session)
    for task, who in await tasks.scheduled(session, date_from=today, date_to=today, open_only=True):
        if task.due_date != today:
            continue
        for x in await employees.by_ids(session, who):
            if x.user_id:
                await notify(
                    session,
                    user_id=x.user_id,
                    kind="task_due",
                    title=f"Due today: {task.number} {task.title}",
                    link=f"/projects/{task.project_id}?tab=tasks",
                    dedupe_key=f"task_due:{task.id}:{today}:{x.user_id}",
                )
                sent += 1
    return sent


async def notifications(
    session: AsyncSession, user_id: uuid.UUID, *, unread_only: bool, limit: int = 50
) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list((await session.execute(stmt)).scalars())


async def unread_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
    ).scalar_one()


async def mark_read(session: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID] | None) -> None:
    stmt = sql_update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    if ids is not None:
        stmt = stmt.where(Notification.id.in_(ids))
    await session.execute(stmt.values(read_at=datetime.now(UTC)))
