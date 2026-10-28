from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from app.core.context import RequestContextMiddleware
from app.core.db import SessionLocal
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.models import import_all_models
from app.modules.attachments.router import router as attachments_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import auth_router, users_router
from app.modules.categories.router import router as categories_router
from app.modules.rbac.router import router as rbac_router
from app.modules.settings import setup as settings_setup
from app.modules.settings.router import router as settings_router

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    configure_logging()
    import_all_models()
    settings_setup.setup()

    app = FastAPI(
        title="ERP API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    v1 = APIRouter(prefix=API_PREFIX)
    for router in (
        auth_router,
        users_router,
        rbac_router,
        audit_router,
        settings_router,
        categories_router,
        attachments_router,
    ):
        v1.include_router(router)
    app.include_router(v1)

    @app.get("/api/health", tags=["health"])
    async def health() -> dict[str, str]:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
