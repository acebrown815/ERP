"""Imports every module's models so SQLAlchemy metadata (and Alembic autogenerate) sees all tables."""


def import_all_models() -> None:
    import app.core.idempotency
    import app.core.numbering
    import app.core.outbox
    import app.modules.attachments.models
    import app.modules.audit.models
    import app.modules.auth.models
    import app.modules.categories.models
    import app.modules.rbac.models
    import app.modules.settings.models  # noqa: F401
