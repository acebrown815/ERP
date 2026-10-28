"""Tests run against a real PostgreSQL database (triggers and constraints matter for an ERP).

Default: the local dev cluster from tools/devdb (database `erp_test`). Override with ERP_TEST_DATABASE_URL.
The schema is rebuilt with Alembic once per run; every test starts from truncated tables plus seed data.
All tests share one event loop (see pyproject.toml) so the connection pool can be reused.
"""

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable

TEST_DB_URL = os.environ.get("ERP_TEST_DATABASE_URL", "postgresql+asyncpg://erp:erp@127.0.0.1:54329/erp_test")
os.environ["ERP_DATABASE_URL"] = TEST_DB_URL
os.environ["ERP_FAST_PASSWORD_HASHING"] = "true"
os.environ["ERP_ENV"] = "test"
os.environ["ERP_ATTACHMENTS_DIR"] = tempfile.mkdtemp(prefix="erp-attachments-")

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.cli import migrate  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.auth import api as auth  # noqa: E402
from app.modules.categories import api as categories  # noqa: E402
from app.modules.rbac import api as rbac  # noqa: E402
from app.modules.settings import api as settings  # noqa: E402

PASSWORD = "Correct-Horse-9"
DELETE_CATEGORY_LEAVES = (
    "DELETE FROM categories c WHERE NOT EXISTS "
    "(SELECT 1 FROM categories k WHERE k.parent_id = c.id OR k.merged_into_id = c.id)"
)


async def _reset_schema() -> None:
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(_reset_schema())
    migrate()


@pytest.fixture(scope="session", autouse=True)
async def dispose_engine(database: None) -> AsyncIterator[None]:
    yield
    await engine.dispose()  # pooled connections must close before the event loop does


@pytest.fixture(autouse=True)
async def clean_db(database: None) -> None:
    # DELETE is far cheaper than TRUNCATE for tiny tables. audit_log is append-only (DELETE is blocked
    # by its trigger), so it is the one table that is truncated.
    async with SessionLocal() as session:
        await session.execute(text("TRUNCATE audit_log"))
        for table in reversed(Base.metadata.sorted_tables):  # children before parents
            if table.name == "audit_log":
                continue
            if table.name == "categories":
                # Self-referencing with ON DELETE RESTRICT (checked row by row): delete leaves first.
                while (await session.execute(text(DELETE_CATEGORY_LEAVES))).rowcount:
                    pass
                continue
            await session.execute(table.delete())
        await rbac.seed_default_roles(session)
        await settings.seed(session, company_name="Test Co")
        await categories.seed(session)
        await session.commit()


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def create_user(email: str, role_key: str | None, *, name: str | None = None, password: str = PASSWORD) -> str:
    async with SessionLocal() as session:
        role_ids = [(await rbac.role_by_key(session, role_key)).id] if role_key else []
        user = await auth.create_user(
            session,
            actor_id=None,
            email=email,
            full_name=name or email.split("@")[0],
            password=password,
            role_ids=role_ids,
        )
        await session.commit()
        return str(user.id)


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    if res.status_code == 200:
        client.headers["X-CSRF-Token"] = res.json()["csrf_token"]
    return res


ClientFactory = Callable[[str | None], Awaitable[httpx.AsyncClient]]


@pytest.fixture
async def client_as() -> AsyncIterator[ClientFactory]:
    """client_as('finance_manager') -> logged-in client for a fresh user with that role."""
    clients: list[httpx.AsyncClient] = []
    counter = 0

    async def factory(role_key: str | None) -> httpx.AsyncClient:
        nonlocal counter
        counter += 1
        email = f"{role_key or 'norole'}{counter}@example.com"
        await create_user(email, role_key)
        client = new_client()
        clients.append(client)
        res = await login(client, email)
        assert res.status_code == 200, res.text
        client.user_id = res.json()["id"]  # type: ignore[attr-defined]
        return client

    yield factory
    for c in clients:
        await c.aclose()


@pytest.fixture
async def admin(client_as: ClientFactory) -> httpx.AsyncClient:
    return await client_as("admin")
