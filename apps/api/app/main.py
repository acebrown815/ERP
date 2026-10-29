from functools import cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.context import RequestContextMiddleware
from app.core.db import SessionLocal
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.models import import_all_models
from app.modules.accounting import setup as accounting_setup
from app.modules.accounting.router import router as accounting_router
from app.modules.attachments.router import router as attachments_router
from app.modules.audit import setup as audit_setup
from app.modules.audit.router import router as audit_router
from app.modules.auth import setup as auth_setup
from app.modules.auth.router import auth_router, users_router
from app.modules.calendar.router import router as calendar_router
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
from app.modules.system.router import router as system_router
from app.modules.tasks import setup as tasks_setup
from app.modules.tasks.router import router as tasks_router

API_PREFIX = "/api/v1"


@cache
def _migration_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


SETUPS = (
    auth_setup,
    audit_setup,
    accounting_setup,
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
    calendar_router,
    system_router,
)


def create_app() -> FastAPI:
    configure_logging()
    import_all_models()
    for module in SETUPS:
        module.setup()

    app = FastAPI(
        title="ERP API",
        version="0.5.0",
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

    @app.get("/api/health/ready", tags=["health"])
    async def ready() -> JSONResponse:
        """For load balancers / monitoring: database reachable and the schema at the latest migration."""
        head = _migration_head()
        async with SessionLocal() as session:
            current = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
        ok = current == head
        return JSONResponse(
            {"status": "ok" if ok else "migration_pending", "database": "ok", "schema": current, "expected": head},
            status_code=200 if ok else 503,
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cache-Control", "no-store")  # API responses carry personal and financial data
        if get_settings().env == "prod":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    return app


app = create_app()
