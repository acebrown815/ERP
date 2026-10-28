from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from app.core.context import RequestContextMiddleware
from app.core.db import SessionLocal
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.models import import_all_models
from app.modules.accounting.router import router as accounting_router
from app.modules.attachments.router import router as attachments_router
from app.modules.audit.router import router as audit_router
from app.modules.auth import setup as auth_setup
from app.modules.auth.router import auth_router, users_router
from app.modules.categories.router import router as categories_router
from app.modules.compensation import setup as compensation_setup
from app.modules.compensation.router import router as compensation_router
from app.modules.employees import setup as employees_setup
from app.modules.employees.router import router as employees_router
from app.modules.imports.router import router as imports_router
from app.modules.parties import setup as parties_setup
from app.modules.parties.router import router as parties_router
from app.modules.payments import setup as payments_setup
from app.modules.payments.router import router as payments_router
from app.modules.projects import setup as projects_setup
from app.modules.projects.router import milestones_router
from app.modules.projects.router import router as projects_router
from app.modules.rbac.router import router as rbac_router
from app.modules.reporting.router import router as reporting_router
from app.modules.salary import setup as salary_setup
from app.modules.salary.router import router as salary_router
from app.modules.settings import setup as settings_setup
from app.modules.settings.router import router as settings_router
from app.modules.tasks import setup as tasks_setup
from app.modules.tasks.router import router as tasks_router

API_PREFIX = "/api/v1"

SETUPS = (
    auth_setup,
    settings_setup,
    parties_setup,
    employees_setup,
    projects_setup,
    payments_setup,
    compensation_setup,
    salary_setup,
    tasks_setup,
)
ROUTERS = (
    auth_router,
    users_router,
    rbac_router,
    audit_router,
    settings_router,
    categories_router,
    attachments_router,
    accounting_router,
    parties_router,
    employees_router,
    projects_router,
    milestones_router,
    payments_router,
    imports_router,
    compensation_router,
    salary_router,
    tasks_router,
    reporting_router,
)


def create_app() -> FastAPI:
    configure_logging()
    import_all_models()
    for module in SETUPS:
        module.setup()

    app = FastAPI(
        title="ERP API",
        version="0.4.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    v1 = APIRouter(prefix=API_PREFIX)
    for router in ROUTERS:
        v1.include_router(router)
    app.include_router(v1)

    @app.get("/api/health", tags=["health"])
    async def health() -> dict[str, str]:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
