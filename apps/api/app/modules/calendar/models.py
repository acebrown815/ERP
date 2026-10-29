import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Authored, Base, UUIDPk

SCOPES = ("personal", "team", "project", "company")
STATUSES = ("confirmed", "requested", "approved", "rejected", "cancelled")
RESPONSES = ("needs_action", "accepted", "declined", "tentative")


class CalendarEvent(UUIDPk, Authored, Base):
    """Meetings, leave, availability and company events (docs/architecture.md, Section 11.3).

    Task dates, milestones and project deadlines are not stored here: the feed derives them at query time.
    Timed events keep UTC instants plus the IANA zone they were created in, so recurrences expand DST-correctly;
    all-day events are plain dates (end inclusive).
    """

    __tablename__ = "calendar_events"
    __table_args__ = (
        CheckConstraint(f"scope IN {SCOPES}", name="scope_valid"),
        CheckConstraint(f"status IN {STATUSES}", name="status_valid"),
        CheckConstraint(
            "(all_day AND start_date IS NOT NULL AND end_date IS NOT NULL AND end_date >= start_date)"
            " OR (NOT all_day AND start_at IS NOT NULL AND end_at IS NOT NULL AND end_at >= start_at)",
            name="times_valid",
        ),
        CheckConstraint("scope <> 'project' OR project_id IS NOT NULL", name="project_scope_has_project"),
        CheckConstraint("scope <> 'team' OR department_id IS NOT NULL", name="team_scope_has_department"),
        Index("ix_calendar_events_owner", "owner_employee_id"),
        Index("ix_calendar_events_range", "start_date", "end_date"),
        Index("ix_calendar_events_range_at", "start_at", "end_at"),
    )

    scope: Mapped[str] = mapped_column(String(10))
    owner_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    event_type_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    event_type_other_text: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(300))
    all_day: Mapped[bool] = mapped_column(default=False)
    start_at: Mapped[datetime | None]
    end_at: Mapped[datetime | None]
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    # RFC 5545 recurrence rule without DTSTART, e.g. "FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20270101T000000Z".
    rrule: Mapped[str | None] = mapped_column(String(500))
    # Minutes before the start at which attendees get an in-app reminder.
    reminders: Mapped[list[int]] = mapped_column(JSONB, default=list)
    # Leave goes requested -> approved / rejected; everything else is confirmed (or cancelled).
    status: Mapped[str] = mapped_column(String(12), default="confirmed")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None]
    decision_note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1)


class EventAttendee(Base):
    __tablename__ = "event_attendees"
    __table_args__ = (CheckConstraint(f"response IN {RESPONSES}", name="response_valid"),)

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calendar_events.id", ondelete="CASCADE"), primary_key=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True)
    response: Mapped[str] = mapped_column(String(12), default="needs_action")


class EventException(Base):
    """One occurrence of a repeating event that was cancelled. `occurrence` is the occurrence's original start
    (ISO date for all-day events, ISO UTC instant otherwise)."""

    __tablename__ = "event_exceptions"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calendar_events.id", ondelete="CASCADE"), primary_key=True)
    occurrence: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Notification(UUIDPk, Base):
    """In-app notification (reminders, leave decisions, ...). `dedupe_key` stops the worker sending one twice."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        Index("ix_notifications_user_unread", "user_id", "read_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    read_at: Mapped[datetime | None]
