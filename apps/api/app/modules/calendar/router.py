import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import Forbidden, NotFound
from app.modules.auth.api import CurrentUser, current_user
from app.modules.calendar import service
from app.modules.calendar.models import CalendarEvent
from app.modules.employees import api as employees
from app.modules.projects import api as projects
from app.modules.rbac.api import Scope
from app.modules.settings import api as settings

router = APIRouter(tags=["calendar"])

EventScope = Literal["personal", "team", "project", "company"]


class AttendeeOut(BaseModel):
    employee_id: uuid.UUID
    name: str
    response: str


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: str
    owner_employee_id: uuid.UUID | None
    department_id: uuid.UUID | None
    project_id: uuid.UUID | None
    event_type_category_id: uuid.UUID | None
    event_type_other_text: str | None
    title: str
    description: str | None
    location: str | None
    all_day: bool
    start_at: datetime | None
    end_at: datetime | None
    start_date: date | None
    end_date: date | None
    timezone: str
    rrule: str | None
    reminders: list[int]
    status: str
    decision_note: str | None
    created_by: uuid.UUID | None
    version: int
    owner_name: str | None = None
    attendees: list[AttendeeOut] = []
    editable: bool = False


class EventIn(BaseModel):
    scope: EventScope = "personal"
    owner_employee_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    event_type_category_id: uuid.UUID | None = None
    event_type_other_text: str | None = Field(default=None, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    location: str | None = Field(default=None, max_length=300)
    all_day: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: str = Field(default="UTC", max_length=64)
    rrule: str | None = Field(default=None, max_length=500)
    reminders: list[int] = Field(default_factory=list, max_length=5)
    attendee_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class EventUpdateIn(BaseModel):
    version: int
    scope: EventScope | None = None
    owner_employee_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    event_type_category_id: uuid.UUID | None = None
    event_type_other_text: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    location: str | None = Field(default=None, max_length=300)
    all_day: bool | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = Field(default=None, max_length=64)
    rrule: str | None = Field(default=None, max_length=500)
    reminders: list[int] | None = Field(default=None, max_length=5)
    attendee_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)


class FeedItem(BaseModel):
    key: str
    kind: str
    title: str
    all_day: bool
    start: str
    end: str
    color: str
    id: uuid.UUID
    occurrence: str | None
    status: str | None
    project_id: uuid.UUID | None
    project_name: str | None
    employee_ids: list[uuid.UUID]
    scope: str | None
    location: str | None
    recurring: bool
    editable: bool
    link: str | None


class FeedOut(BaseModel):
    date_from: date
    date_to: date
    items: list[FeedItem]
    people: dict[str, str]  # employee id -> name, for labels


class DayOut(BaseModel):
    date: date
    capacity: Decimal
    meetings: Decimal
    tasks: Decimal
    load: Decimal
    on_leave: bool


class WorkloadRow(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    days: list[DayOut]
    capacity: Decimal
    load: Decimal


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=2000)


class RespondIn(BaseModel):
    response: Literal["accepted", "declined", "tentative"]


class OccurrenceIn(BaseModel):
    occurrence: str = Field(min_length=10, max_length=40)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str | None
    link: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationsOut(BaseModel):
    unread: int
    items: list[NotificationOut]


class ReadIn(BaseModel):
    ids: list[uuid.UUID] | None = None  # None = all


async def _out(session: AsyncSession, v: service.Viewer, e: CalendarEvent) -> EventOut:
    att = (await service.attendees_of(session, [e.id])).get(e.id, [])
    names = await employees.names(session, [x for x in [e.owner_employee_id, *(a for a, _ in att)] if x])
    if not await service.can_see(session, v, e, [a for a, _ in att]):
        raise NotFound("Event not found")
    out = EventOut.model_validate(e)
    out.owner_name = names.get(e.owner_employee_id) if e.owner_employee_id else None
    out.attendees = [AttendeeOut(employee_id=a, name=names.get(a, "?"), response=r) for a, r in att]
    out.editable = service._can_manage_scope(v, e) or e.created_by == v.user.id
    return out


@router.get("/calendar/feed", response_model=FeedOut)
async def feed(
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    view: Literal["me", "team", "company"] = "me",
    department_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> FeedOut:
    """Events (repeats expanded, minus cancelled occurrences) plus tasks, milestones and project deadlines,
    derived at query time so a changed task date shows up immediately (docs/architecture.md, Section 11.3)."""
    # The team and company views show colleagues' leave; restricted access is their own calendar only.
    if view != "me" and user.restricted:
        raise Forbidden("Only your own calendar is available with restricted access")
    v = await service.viewer(session, user)
    items = await service.feed(
        session, v, date_from=date_from, date_to=date_to, view=view, department_id=department_id, project_id=project_id
    )
    people = await employees.names(session, list({e for i in items for e in i.employee_ids}))
    return FeedOut(
        date_from=date_from,
        date_to=date_to,
        items=[FeedItem(**vars(i)) for i in items],
        people={str(k): val for k, val in people.items()},
    )


@router.get("/calendar/events/{event_id}", response_model=EventOut)
async def get_event(
    event_id: uuid.UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> EventOut:
    v = await service.viewer(session, user)
    return await _out(session, v, await service.get(session, event_id))


@router.post("/calendar/events", response_model=EventOut, status_code=201)
async def create_event(
    body: EventIn, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> EventOut:
    v = await service.viewer(session, user)
    e = await service.create(
        session, v=v, data=body.model_dump(exclude={"attendee_ids"}), attendee_ids=body.attendee_ids
    )
    await session.commit()
    return await _out(session, v, e)


@router.patch("/calendar/events/{event_id}", response_model=EventOut)
async def update_event(
    event_id: uuid.UUID,
    body: EventUpdateIn,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> EventOut:
    v = await service.viewer(session, user)
    e = await service.update(
        session,
        v=v,
        event_id=event_id,
        version=body.version,
        changes=body.model_dump(exclude_unset=True, exclude={"version", "attendee_ids"}),
        attendee_ids=body.attendee_ids,
    )
    await session.commit()
    return await _out(session, v, e)


@router.delete("/calendar/events/{event_id}", status_code=204)
async def delete_event(
    event_id: uuid.UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> Response:
    await service.delete_event(session, v=await service.viewer(session, user), event_id=event_id)
    await session.commit()
    return Response(status_code=204)


@router.post("/calendar/events/{event_id}/cancel-occurrence", status_code=204)
async def cancel_occurrence(
    event_id: uuid.UUID,
    body: OccurrenceIn,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Skip one occurrence of a repeating event."""
    await service.cancel_occurrence(
        session, v=await service.viewer(session, user), event_id=event_id, occurrence=body.occurrence
    )
    await session.commit()
    return Response(status_code=204)


@router.post("/calendar/events/{event_id}/respond", status_code=204)
async def respond(
    event_id: uuid.UUID,
    body: RespondIn,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await service.respond(session, v=await service.viewer(session, user), event_id=event_id, response=body.response)
    await session.commit()
    return Response(status_code=204)


@router.post("/calendar/events/{event_id}/decision", response_model=EventOut)
async def decide(
    event_id: uuid.UUID,
    body: DecisionIn,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> EventOut:
    """Approve or reject a leave request (leave.approve)."""
    v = await service.viewer(session, user)
    e = await service.decide_leave(session, v=v, event_id=event_id, approve=body.approve, note=body.note)
    await session.commit()
    return await _out(session, v, e)


@router.get("/calendar/leave/pending", response_model=list[EventOut])
async def pending_leave(
    user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> list[EventOut]:
    v = await service.viewer(session, user)
    return [await _out(session, v, e) for e in await service.pending_leave(session, v)]


@router.get("/calendar/workload", response_model=list[WorkloadRow])
async def workload(
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    department_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[WorkloadRow]:
    """Per person per day: capacity vs meetings + task estimates (Section 11.3). A project team, a department,
    or (without either) just you."""
    v = await service.viewer(session, user)
    if project_id:
        await projects.ensure_visible(session, user, "projects.read", await projects.get(session, project_id))
        people = list(await projects.team_ids(session, {project_id}))
    elif department_id:
        if department_id != v.department_id and not user.can("employees.read", Scope.ALL):
            raise Forbidden("You can only see your own team's workload")
        people = [e.id for e in await employees.active_in(session, department_id=department_id)]
    else:
        people = [v.employee_id] if v.employee_id else []
    names = await employees.names(session, people)
    data = await service.workload(
        session, employee_ids=people, date_from=date_from, date_to=date_to, today=await settings.today(session)
    )
    rows = []
    for emp, days in data.items():
        rows.append(
            WorkloadRow(
                employee_id=emp,
                employee_name=names.get(emp, "?"),
                days=[
                    DayOut(
                        date=d.date,
                        capacity=d.capacity,
                        meetings=d.meetings,
                        tasks=d.tasks,
                        load=d.load,
                        on_leave=d.on_leave,
                    )
                    for d in days
                ],
                capacity=sum((d.capacity for d in days), Decimal(0)),
                load=sum((d.load for d in days), Decimal(0)),
            )
        )
    rows.sort(key=lambda r: r.employee_name.lower())
    return rows


# ---- notifications ---------------------------------------------------------------------------------


@router.get("/notifications", response_model=NotificationsOut)
async def list_notifications(
    unread_only: bool = False, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> NotificationsOut:
    items = await service.notifications(session, user.id, unread_only=unread_only)
    return NotificationsOut(
        unread=await service.unread_count(session, user.id), items=[NotificationOut.model_validate(n) for n in items]
    )


@router.post("/notifications/read", status_code=204)
async def read_notifications(
    body: ReadIn, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> Response:
    await service.mark_read(session, user.id, body.ids)
    await session.commit()
    return Response(status_code=204)
