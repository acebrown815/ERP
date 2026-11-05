import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import Forbidden, Unauthorized
from app.core.security import tokens_equal
from app.modules.auth import service
from app.modules.rbac import api as rbac

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Everything a restricted sign-in (hired manager, contractor, freelancer) may call. Anything else is refused, including
# routes added later, so giving them access to something new is a decision. Permissions and project checks still apply.
_UUID = r"[0-9a-fA-F-]{36}"
RESTRICTED_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (methods, re.compile(f"^/api/v1{path}$"))
    for methods, path in (
        ("GET", "/auth/me"),
        ("POST", "/auth/(logout|logout-all|change-password)"),
        ("GET", "/employees/me"),
        ("GET", "/notifications"),
        ("POST", "/notifications/read"),
        ("GET", "/calendar/feed"),
        # What their screens need to display things; cut down further by those routes.
        ("GET", "/settings/company"),
        ("GET", "/currencies"),
        ("GET", "/categories(/groups)?"),
        # Their work, limited to the projects they're connected to: tasks can change, projects are read-only.
        ("GET", "/projects"),
        ("GET", "/projects/my-managers"),
        ("GET", f"/projects/{_UUID}"),
        ("GET", f"/projects/{_UUID}/milestones"),
        ("GET", f"/projects/{_UUID}/timeline"),
        ("GET,POST", "/tasks"),
        ("GET", "/tasks/progress"),
        ("GET,PATCH,DELETE", f"/tasks/{_UUID}"),
        ("POST", f"/tasks/{_UUID}/(move|dependencies)"),
        ("DELETE", f"/tasks/{_UUID}/dependencies/{_UUID}"),
        ("GET,POST", f"/tasks/{_UUID}/(time-entries|comments)"),
        ("PATCH,DELETE", f"/(time-entries|task-comments)/{_UUID}"),
        ("GET,POST", "/attachments"),
        ("GET", f"/attachments/{_UUID}/download"),
        ("DELETE", f"/attachments/{_UUID}"),
        # Their own pay, limited to it by the payments routes.
        ("GET", f"/payment-entries(/totals|/{_UUID})?"),
    )
)


def restricted_may_call(method: str, path: str) -> bool:
    return any(method in methods.split(",") and pattern.match(path) for methods, pattern in RESTRICTED_ROUTES)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    full_name: str
    session_id: uuid.UUID
    grants: Mapping[str, rbac.Scope]
    restricted: bool = False  # a hired manager, contractor or freelancer, whatever role their sign-in holds

    def scope_for(self, permission: str) -> rbac.Scope | None:
        return self.grants.get(permission)

    def can(self, permission: str, scope: rbac.Scope = rbac.Scope.OWN) -> bool:
        granted = self.grants.get(permission)
        return granted is not None and granted.rank >= scope.rank


async def _restricted_record(session: AsyncSession, user_id: uuid.UUID):  # type: ignore[no-untyped-def]
    from app.modules.employees import api as employees  # imported here: employees depends on this module

    own = await employees.for_user(session, user_id)
    return own if own is not None and await employees.is_restricted(session, own) else None


async def user_grants(session: AsyncSession, user_id: uuid.UUID) -> dict[str, rbac.Scope]:
    """The user's permissions. A restricted sign-in's are fixed, so selecting a different role can't widen them, and
    someone who has left has none."""
    record = await _restricted_record(session, user_id)
    if record is None:
        return await rbac.effective_grants(session, user_id)
    return {} if record.status == "terminated" else rbac.restricted_grants()


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> CurrentUser:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise Unauthorized()
    user_session, user = await service.resolve_session(session, token)

    if request.method not in SAFE_METHODS:
        sent = request.headers.get(settings.csrf_header_name, "")
        if not sent or not tokens_equal(sent, user_session.csrf_token):
            raise Forbidden("Missing or invalid CSRF token")

    restricted = await _restricted_record(session, user.id) is not None
    if restricted and not restricted_may_call(request.method, request.url.path):
        raise Forbidden("Not available with restricted access")
    grants = await user_grants(session, user.id)
    current = CurrentUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        session_id=user_session.id,
        grants=grants,
        restricted=restricted,
    )
    request.state.user_id = user.id
    return current


def require(permission: str, scope: rbac.Scope = rbac.Scope.OWN) -> Callable[..., Awaitable[CurrentUser]]:
    """Dependency that requires `permission` with at least `scope`. Row-level filtering by the
    granted scope is the caller's job (use `user.scope_for(permission)`)."""
    rbac.get_permission(permission)  # fail fast on typos at import time

    async def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not user.can(permission, scope):
            raise Forbidden(f"Requires permission {permission}")
        return user

    return dependency


def require_any(*permissions: str) -> Callable[..., Awaitable[CurrentUser]]:
    for p in permissions:
        rbac.get_permission(p)

    async def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not any(user.can(p) for p in permissions):
            raise Forbidden(f"Requires one of: {', '.join(permissions)}")
        return user

    return dependency
