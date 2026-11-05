import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.pagination import Page, PageParams, page_params, paginate
from app.modules.auth import service
from app.modules.auth.deps import CurrentUser, current_user, require, user_grants
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    ChangePasswordIn,
    LoginIn,
    MeOut,
    RoleRef,
    SetPasswordIn,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)
from app.modules.rbac import api as rbac

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


def _set_session_cookies(response: Response, token: str, csrf: str) -> None:
    s = get_settings()
    max_age = s.session_absolute_hours * 3600
    response.set_cookie(
        s.session_cookie_name, token, max_age=max_age, httponly=True, secure=s.cookie_secure, samesite="lax", path="/"
    )
    response.set_cookie(
        s.csrf_cookie_name, csrf, max_age=max_age, httponly=False, secure=s.cookie_secure, samesite="lax", path="/"
    )


def _clear_session_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(s.session_cookie_name, path="/")
    response.delete_cookie(s.csrf_cookie_name, path="/")


async def _me(session: AsyncSession, user_id: uuid.UUID, csrf: str) -> MeOut:
    from app.modules.employees import api as employees  # imported here: employees depends on this module

    user = await service.get_user(session, user_id)
    own = await employees.for_user(session, user.id)
    roles = (await rbac.roles_by_user(session, [user.id]))[user.id]
    grants = await user_grants(session, user.id)
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        roles=[RoleRef.model_validate(r) for r in roles],
        permissions={k: v.value for k, v in sorted(grants.items())},
        restricted_access=bool(own and await employees.is_restricted(session, own)),
        # Staff can set a hire on any project they manage; employees only if they're full-time.
        can_select_hire="projects.manage" in grants
        or ("projects.create_own" in grants and bool(own and await employees.is_full_time(session, own))),
        csrf_token=csrf,
    )


@auth_router.post("/login", response_model=MeOut)
async def login(
    body: LoginIn, request: Request, response: Response, session: AsyncSession = Depends(get_session)
) -> MeOut:
    result = await service.login(
        session,
        email=body.email,
        password=body.password,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    _set_session_cookies(response, result.token, result.session.csrf_token)
    return await _me(session, result.user.id, result.session.csrf_token)


@auth_router.post("/logout", status_code=204)
async def logout(
    response: Response, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> Response:
    await service.logout(session, session_id=user.session_id, user_id=user.id)
    await session.commit()
    response.status_code = 204
    _clear_session_cookies(response)
    return response


@auth_router.post("/logout-all", status_code=204)
async def logout_all(
    response: Response, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> Response:
    await service.revoke_all_sessions(session, user.id)
    await session.commit()
    response.status_code = 204
    _clear_session_cookies(response)
    return response


@auth_router.get("/me", response_model=MeOut)
async def me(
    request: Request, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> MeOut:
    csrf = request.cookies.get(get_settings().csrf_cookie_name, "")
    return await _me(session, user.id, csrf)


@auth_router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordIn, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(get_session)
) -> Response:
    await service.change_password(
        session, user_id=user.id, session_id=user.session_id, current=body.current_password, new=body.new_password
    )
    await session.commit()
    return Response(status_code=204)


# ---- users -----------------------------------------------------------------------------------------


async def _users_out(session: AsyncSession, users: list[User]) -> list[UserOut]:
    roles = await rbac.roles_by_user(session, [u.id for u in users])
    now = datetime.now(UTC)
    return [
        UserOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            is_active=u.is_active,
            is_locked=bool(u.locked_until and u.locked_until > now),
            last_login_at=u.last_login_at,
            created_at=u.created_at,
            version=u.version,
            roles=[RoleRef.model_validate(r) for r in roles[u.id]],
        )
        for u in users
    ]


@users_router.get("", response_model=Page[UserOut])
async def list_users(
    params: PageParams = Depends(page_params),
    q: Annotated[str | None, Query(max_length=100)] = None,
    is_active: bool | None = None,
    _: CurrentUser = Depends(require("users.manage")),
    session: AsyncSession = Depends(get_session),
) -> Page[UserOut]:
    stmt = await service.list_users(session, q=q, is_active=is_active)
    users, total = await paginate(session, stmt, params)
    return Page(items=await _users_out(session, users), total=total, page=params.page, page_size=params.page_size)


@users_router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID, _: CurrentUser = Depends(require("users.manage")), session: AsyncSession = Depends(get_session)
) -> UserOut:
    return (await _users_out(session, [await service.get_user(session, user_id)]))[0]


@users_router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreateIn,
    actor: CurrentUser = Depends(require("users.manage")),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    user = await service.create_user(
        session,
        actor_id=actor.id,
        email=body.email,
        full_name=body.full_name,
        password=body.password,
        role_ids=body.role_ids,
    )
    await session.commit()
    return (await _users_out(session, [user]))[0]


@users_router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateIn,
    actor: CurrentUser = Depends(require("users.manage")),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    user = await service.update_user(
        session,
        actor_id=actor.id,
        user_id=user_id,
        version=body.version,
        full_name=body.full_name,
        is_active=body.is_active,
        role_ids=body.role_ids,
    )
    await session.commit()
    return (await _users_out(session, [user]))[0]


@users_router.post("/{user_id}/set-password", status_code=204)
async def set_password(
    user_id: uuid.UUID,
    body: SetPasswordIn,
    actor: CurrentUser = Depends(require("users.manage")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await service.set_password(session, actor_id=actor.id, user_id=user_id, password=body.password)
    await session.commit()
    return Response(status_code=204)
