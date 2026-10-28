import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    Conflict,
    Forbidden,
    NotFound,
    PreconditionFailed,
    TooManyRequests,
    Unauthorized,
    ValidationFailed,
    field_error,
)
from app.core.security import hash_password, hash_token, needs_rehash, new_token, verify_password
from app.modules.audit import api as audit
from app.modules.auth.models import User, UserSession
from app.modules.rbac import api as rbac

TOUCH_INTERVAL = timedelta(minutes=5)


@dataclass
class LoginResult:
    user: User
    session: UserSession
    token: str


def _now() -> datetime:
    return datetime.now(UTC)


def _check_password_policy(password: str, field: str = "password") -> None:
    min_len = get_settings().password_min_length
    if len(password) < min_len:
        raise ValidationFailed(
            "Password is too short",
            errors=[field_error(field, f"Use at least {min_len} characters", "too_short")],
        )


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return (
        await session.execute(select(User).where(func.lower(User.email) == email.strip().lower()))
    ).scalar_one_or_none()


async def login(
    session: AsyncSession, *, email: str, password: str, ip: str | None, user_agent: str | None
) -> LoginResult:
    """Verify credentials and open a session. Commits failure counters before raising."""
    settings = get_settings()
    user = await get_user_by_email(session, email)
    now = _now()

    if user is not None and user.locked_until and user.locked_until > now:
        await audit.record(
            session, actor_id=user.id, action="auth.login_blocked", entity_type="user", entity_id=user.id
        )
        await session.commit()
        raise TooManyRequests("Too many failed attempts. Try again later.")

    ok = verify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active:
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
        await audit.record(
            session,
            actor_id=user.id if user else None,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id if user else None,
            after={"email": email.strip().lower()},
        )
        await session.commit()
        raise Unauthorized("Invalid email or password")

    if needs_rehash(user.password_hash or ""):
        user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    token = new_token()
    user_session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=new_token(),
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        ip=ip,
        user_agent=(user_agent or "")[:500] or None,
    )
    session.add(user_session)
    await session.flush()
    await audit.record(session, actor_id=user.id, action="auth.login", entity_type="user", entity_id=user.id)
    return LoginResult(user=user, session=user_session, token=token)


async def resolve_session(session: AsyncSession, token: str) -> tuple[UserSession, User]:
    settings = get_settings()
    now = _now()
    row = (
        await session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == hash_token(token))
        )
    ).first()
    if row is None:
        raise Unauthorized("Session expired. Please sign in again.")
    user_session, user = row
    idle_deadline = user_session.last_seen_at + timedelta(minutes=settings.session_idle_minutes)
    if user_session.revoked_at or user_session.expires_at <= now or idle_deadline <= now or not user.is_active:
        raise Unauthorized("Session expired. Please sign in again.")
    if now - user_session.last_seen_at > TOUCH_INTERVAL:
        user_session.last_seen_at = now
        await session.commit()
    return user_session, user


async def logout(session: AsyncSession, *, session_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await session.execute(update(UserSession).where(UserSession.id == session_id).values(revoked_at=_now()))
    await audit.record(session, actor_id=user_id, action="auth.logout", entity_type="user", entity_id=user_id)


async def revoke_all_sessions(session: AsyncSession, user_id: uuid.UUID, *, except_id: uuid.UUID | None = None) -> None:
    stmt = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_id is not None:
        stmt = stmt.where(UserSession.id != except_id)
    await session.execute(stmt.values(revoked_at=_now()))


async def change_password(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID, current: str, new: str
) -> None:
    user = await get_user(session, user_id)
    if not verify_password(user.password_hash, current):
        raise ValidationFailed(
            "Current password is wrong",
            errors=[field_error("current_password", "Current password is wrong", "wrong_password")],
        )
    _check_password_policy(new, "new_password")
    user.password_hash = hash_password(new)
    user.password_changed_at = _now()
    await revoke_all_sessions(session, user.id, except_id=session_id)
    await audit.record(session, actor_id=user.id, action="user.password_changed", entity_type="user", entity_id=user.id)


# ---- user administration -------------------------------------------------------------------------


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    return user


async def list_users(session: AsyncSession, *, q: str | None, is_active: bool | None):  # type: ignore[no-untyped-def]
    stmt = select(User).order_by(User.full_name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.email.ilike(like)))
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    return stmt


def _snapshot(user: User) -> dict:
    return {"email": user.email, "full_name": user.full_name, "is_active": user.is_active}


async def create_user(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    email: str,
    full_name: str,
    password: str,
    role_ids: list[uuid.UUID],
) -> User:
    _check_password_policy(password)
    if await get_user_by_email(session, email):
        raise Conflict("A user with this email already exists")
    user = User(
        email=email.strip().lower(),
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        password_changed_at=_now(),
    )
    session.add(user)
    await session.flush()
    await audit.record(
        session, actor_id=actor_id, action="user.created", entity_type="user", entity_id=user.id, after=_snapshot(user)
    )
    if role_ids:
        if actor_id is None:  # bootstrap (CLI) path
            await rbac.assign_roles_system(session, user_id=user.id, role_ids=role_ids)
        else:
            await rbac.set_user_roles(session, actor_id=actor_id, user_id=user.id, role_ids=role_ids)
    return user


async def update_user(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    user_id: uuid.UUID,
    version: int,
    full_name: str | None,
    is_active: bool | None,
    role_ids: list[uuid.UUID] | None,
) -> User:
    user = await get_user(session, user_id)
    if user.version != version:
        raise PreconditionFailed()
    before = _snapshot(user)

    if is_active is False and user.id == actor_id:
        raise Forbidden("You cannot deactivate your own account")
    was_admin = user.is_active and user.id in await rbac.admin_user_ids(session)

    if full_name is not None:
        user.full_name = full_name.strip()
    if is_active is not None and is_active != user.is_active:
        user.is_active = is_active
        if not is_active:
            await revoke_all_sessions(session, user.id)
    if role_ids is not None:
        await rbac.set_user_roles(session, actor_id=actor_id, user_id=user.id, role_ids=role_ids)

    await session.flush()
    if was_admin and await _active_admin_count(session) == 0:
        raise Conflict("At least one active Administrator is required")

    user.version += 1
    b, a = audit.diff(before, _snapshot(user))
    if a:
        await audit.record(
            session, actor_id=actor_id, action="user.updated", entity_type="user", entity_id=user.id, before=b, after=a
        )
    return user


async def _active_admin_count(session: AsyncSession) -> int:
    admin_ids = await rbac.admin_user_ids(session)
    if not admin_ids:
        return 0
    return (
        await session.execute(select(func.count()).where(User.id.in_(admin_ids), User.is_active.is_(True)))
    ).scalar_one()


async def set_password(session: AsyncSession, *, actor_id: uuid.UUID, user_id: uuid.UUID, password: str) -> None:
    _check_password_policy(password)
    user = await get_user(session, user_id)
    user.password_hash = hash_password(password)
    user.password_changed_at = _now()
    user.failed_login_count = 0
    user.locked_until = None
    await revoke_all_sessions(session, user.id)
    await audit.record(session, actor_id=actor_id, action="user.password_reset", entity_type="user", entity_id=user.id)
