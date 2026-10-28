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


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    full_name: str
    session_id: uuid.UUID
    grants: Mapping[str, rbac.Scope]

    def scope_for(self, permission: str) -> rbac.Scope | None:
        return self.grants.get(permission)

    def can(self, permission: str, scope: rbac.Scope = rbac.Scope.OWN) -> bool:
        granted = self.grants.get(permission)
        return granted is not None and granted.rank >= scope.rank


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

    grants = await rbac.effective_grants(session, user.id)
    current = CurrentUser(
        id=user.id, email=user.email, full_name=user.full_name, session_id=user_session.id, grants=grants
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
