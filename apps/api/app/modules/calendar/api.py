"""Public facade of the calendar module."""

from app.modules.calendar.service import notify, send_reminders

__all__ = ["notify", "send_reminders"]
