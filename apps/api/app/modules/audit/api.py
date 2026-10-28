"""Public facade of the audit module."""

from app.modules.audit.service import diff, record

__all__ = ["diff", "record"]
