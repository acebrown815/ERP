from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core.db import SessionLocal
from app.modules.auth.models import User, UserSession
from tests.conftest import PASSWORD, ClientFactory, create_user, login, new_client


async def test_login_sets_cookies_and_me_returns_permissions() -> None:
    await create_user("fm@example.com", "finance_manager", name="Fiona")
    async with new_client() as c:
        res = await login(c, "FM@Example.com")  # email is case-insensitive
        assert res.status_code == 200
        assert "erp_session" in c.cookies and "erp_csrf" in c.cookies
        body = res.json()
        assert body["full_name"] == "Fiona"
        assert body["roles"][0]["key"] == "finance_manager"
        assert body["permissions"]["payments.submit"] == "all"
        assert "users.manage" not in body["permissions"]

        me = await c.get("/api/v1/auth/me")
        assert me.status_code == 200 and me.json()["email"] == "fm@example.com"


async def test_wrong_password_and_unknown_user_look_the_same() -> None:
    await create_user("a@example.com", "employee")
    async with new_client() as c:
        wrong = await login(c, "a@example.com", "nope-nope-nope")
        unknown = await login(c, "ghost@example.com", "nope-nope-nope")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


async def test_lockout_after_repeated_failures() -> None:
    await create_user("a@example.com", "employee")
    async with new_client() as c:
        for _ in range(5):
            assert (await login(c, "a@example.com", "bad-password-x")).status_code == 401
        locked = await login(c, "a@example.com")  # even the right password is refused while locked
        assert locked.status_code == 429


async def test_inactive_user_cannot_login() -> None:
    await create_user("a@example.com", "employee")
    async with SessionLocal() as s:
        await s.execute(update(User).values(is_active=False))
        await s.commit()
    async with new_client() as c:
        assert (await login(c, "a@example.com")).status_code == 401


async def test_unauthenticated_requests_are_rejected() -> None:
    async with new_client() as c:
        res = await c.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert res.headers["content-type"].startswith("application/problem+json")


async def test_csrf_token_required_for_unsafe_methods(client_as: ClientFactory) -> None:
    c = await client_as("admin")
    token = c.headers.pop("X-CSRF-Token")
    res = await c.post("/api/v1/categories", json={"group_key": "payment_method", "name": "Wise"})
    assert res.status_code == 403
    c.headers["X-CSRF-Token"] = "forged"
    assert (await c.post("/api/v1/categories", json={"group_key": "payment_method", "name": "Wise"})).status_code == 403
    c.headers["X-CSRF-Token"] = token
    assert (await c.post("/api/v1/categories", json={"group_key": "payment_method", "name": "Wise"})).status_code == 201


async def test_logout_revokes_session(client_as: ClientFactory) -> None:
    c = await client_as("employee")
    session_cookie = c.cookies["erp_session"]
    assert (await c.post("/api/v1/auth/logout")).status_code == 204
    c.cookies.set("erp_session", session_cookie)  # replaying the old cookie must not work
    assert (await c.get("/api/v1/auth/me")).status_code == 401


async def test_idle_session_expires(client_as: ClientFactory) -> None:
    c = await client_as("employee")
    async with SessionLocal() as s:
        await s.execute(update(UserSession).values(last_seen_at=datetime.now(UTC) - timedelta(days=1)))
        await s.commit()
    assert (await c.get("/api/v1/auth/me")).status_code == 401


async def test_change_password_revokes_other_sessions() -> None:
    await create_user("a@example.com", "employee")
    async with new_client() as first, new_client() as second:
        await login(first, "a@example.com")
        await login(second, "a@example.com")
        short = await first.post(
            "/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"}
        )
        assert short.status_code == 422
        res = await first.post(
            "/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": "A-much-better-one-1"}
        )
        assert res.status_code == 204
        assert (await first.get("/api/v1/auth/me")).status_code == 200
        assert (await second.get("/api/v1/auth/me")).status_code == 401
    async with new_client() as c:
        assert (await login(c, "a@example.com", "A-much-better-one-1")).status_code == 200
