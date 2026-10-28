import pytest

from app.modules.rbac.defaults import DEFAULT_ROLES
from app.modules.rbac.permissions import PERMISSIONS
from tests.conftest import ClientFactory, login, new_client


def test_default_role_grants_are_valid() -> None:
    for role in DEFAULT_ROLES:
        for key, scope in role["grants"].items():
            assert key in PERMISSIONS, key
            assert scope in PERMISSIONS[key].scopes, (role["key"], key, scope)


async def _role_id(c, key: str) -> str:  # type: ignore[no-untyped-def]
    roles = (await c.get("/api/v1/roles")).json()
    return next(r["id"] for r in roles if r["key"] == key)


async def test_admin_creates_user_who_can_log_in(admin) -> None:  # type: ignore[no-untyped-def]
    res = await admin.post(
        "/api/v1/users",
        json={
            "email": "New.Person@example.com",
            "full_name": "New Person",
            "password": "Welcome-2026!",
            "role_ids": [await _role_id(admin, "project_manager")],
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["email"] == "new.person@example.com"
    assert res.json()["roles"][0]["key"] == "project_manager"

    dup = await admin.post(
        "/api/v1/users", json={"email": "new.person@EXAMPLE.com", "full_name": "x", "password": "Welcome-2026!"}
    )
    assert dup.status_code == 409

    async with new_client() as c:
        assert (await login(c, "new.person@example.com", "Welcome-2026!")).status_code == 200

    listed = (await admin.get("/api/v1/users", params={"q": "new per"})).json()
    assert listed["total"] == 1


@pytest.mark.parametrize("role", ["finance_manager", "project_manager", "employee"])
async def test_non_admins_cannot_manage_users_or_roles(client_as: ClientFactory, role: str) -> None:
    c = await client_as(role)
    assert (await c.get("/api/v1/users")).status_code == 403
    assert (await c.get("/api/v1/roles")).status_code == 403
    assert (
        await c.post("/api/v1/users", json={"email": "x@example.com", "full_name": "x", "password": "Welcome-2026!"})
    ).status_code == 403


async def test_cannot_change_own_roles_or_deactivate_self(admin) -> None:  # type: ignore[no-untyped-def]
    me = (await admin.get(f"/api/v1/users/{admin.user_id}")).json()
    res = await admin.patch(f"/api/v1/users/{admin.user_id}", json={"version": me["version"], "role_ids": []})
    assert res.status_code == 403
    res = await admin.patch(f"/api/v1/users/{admin.user_id}", json={"version": me["version"], "is_active": False})
    assert res.status_code == 403


async def test_stale_version_is_rejected(admin, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    other = await client_as("employee")
    user = (await admin.get(f"/api/v1/users/{other.user_id}")).json()
    ok = await admin.patch(f"/api/v1/users/{other.user_id}", json={"version": user["version"], "full_name": "A"})
    assert ok.status_code == 200
    stale = await admin.patch(f"/api/v1/users/{other.user_id}", json={"version": user["version"], "full_name": "B"})
    assert stale.status_code == 412


async def test_deactivating_user_ends_their_sessions(admin, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    other = await client_as("employee")
    user = (await admin.get(f"/api/v1/users/{other.user_id}")).json()
    await admin.patch(f"/api/v1/users/{other.user_id}", json={"version": user["version"], "is_active": False})
    assert (await other.get("/api/v1/auth/me")).status_code == 401


async def test_role_changes_take_effect_immediately(admin, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    other = await client_as("employee")
    assert (await other.get("/api/v1/audit-logs")).status_code == 403
    user = (await admin.get(f"/api/v1/users/{other.user_id}")).json()
    await admin.patch(
        f"/api/v1/users/{other.user_id}",
        json={"version": user["version"], "role_ids": [await _role_id(admin, "finance_manager")]},
    )
    assert (await other.get("/api/v1/audit-logs")).status_code == 200


async def test_custom_role_lifecycle(admin) -> None:  # type: ignore[no-untyped-def]
    bad = await admin.post(
        "/api/v1/roles", json={"key": "auditor", "name": "Auditor", "grants": {"users.manage": "own"}}
    )
    assert bad.status_code == 422  # users.manage only supports scope 'all'
    unknown = await admin.post(
        "/api/v1/roles", json={"key": "auditor", "name": "Auditor", "grants": {"nope.read": "all"}}
    )
    assert unknown.status_code == 422

    res = await admin.post(
        "/api/v1/roles",
        json={"key": "auditor", "name": "Auditor", "grants": {"audit.read": "all", "reports.financial": "all"}},
    )
    assert res.status_code == 201
    role = res.json()
    upd = await admin.patch(f"/api/v1/roles/{role['id']}", json={"grants": {"audit.read": "all"}})
    assert upd.json()["grants"] == {"audit.read": "all"}

    admin_role = await _role_id(admin, "admin")
    assert (await admin.patch(f"/api/v1/roles/{admin_role}", json={"grants": {}})).status_code == 403
    assert (await admin.delete(f"/api/v1/roles/{admin_role}")).status_code == 403
    assert (await admin.delete(f"/api/v1/roles/{role['id']}")).status_code == 204


async def test_permissions_catalog(admin) -> None:  # type: ignore[no-untyped-def]
    perms = (await admin.get("/api/v1/permissions")).json()
    keys = {p["key"] for p in perms}
    assert {"payments.submit", "salary.close_period", "categories.manage.finance"} <= keys
