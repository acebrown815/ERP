"""Imports every module's models so SQLAlchemy metadata (and Alembic autogenerate) sees all tables."""


def import_all_models() -> None:
    import app.core.idempotency
    import app.core.numbering
    import app.core.outbox
    import app.modules.accounting.models
    import app.modules.attachments.models
    import app.modules.attribution.models
    import app.modules.audit.models
    import app.modules.auth.models
    import app.modules.categories.models
    import app.modules.compensation.models
    import app.modules.employees.models
    import app.modules.parties.models
    import app.modules.payments.models
    import app.modules.projects.models
    import app.modules.rbac.models
    import app.modules.salary.models
    import app.modules.settings.models  # noqa: F401
