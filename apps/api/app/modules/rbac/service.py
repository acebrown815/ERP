import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed, field_error
from app.modules.audit import api as audit
from app.modules.rbac.defaults import DEFAULT_ROLES
from app.modules.rbac.models import Role, RolePermission, UserRole
from app.modules.rbac.permissions import PERMISSIONS, Scope


async def effective_grants(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Scope]:
    """Highest scope per permission across all of the user's roles."""
    roles = (
        (
            await session.execute(
                select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    if any(r.grants_all for r in roles):
        return {key: Scope.ALL for key in PERMISSIONS}

    rows = (
        await session.execute(
            select(RolePermission.permission, RolePermission.scope)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
    ).all()
    grants: dict[str, Scope] = {}
    for permission, scope in rows:
        if permission not in PERMISSIONS:
            continue  # permission removed from code; ignore stale grant
        s = Scope(scope)
        if permission not in grants or s.rank > grants[permission].rank:
            grants[permission] = s
    return grants


def _validate_grants(grants: dict[str, str]) -> dict[str, Scope]:
    errors = []
    clean: dict[str, Scope] = {}
    for key, scope in grants.items():
        perm = PERMISSIONS.get(key)
        if perm is None:
            errors.append(field_error(f"grants.{key}", "Unknown permission", "unknown_permission"))
            continue
        try:
            s = Scope(scope)
        except ValueError:
            errors.append(field_error(f"grants.{key}", f"Unknown scope {scope!r}", "invalid_scope"))
            continue
        if s not in perm.scopes:
            allowed = ", ".join(x.value for x in perm.scopes)
            errors.append(field_error(f"grants.{key}", f"Scope must be one of: {allowed}", "invalid_scope"))
            continue
        clean[key] = s
    if errors:
        raise ValidationFailed("Invalid permission grants", errors=errors)
    return clean


async def role_grants(session: AsyncSession, role_id: uuid.UUID) -> dict[str, Scope]:
    rows = (await session.execute(select(RolePermission).where(RolePermission.role_id == role_id))).scalars().all()
    return {r.permission: Scope(r.scope) for r in rows}


async def list_roles(session: AsyncSession) -> list[tuple[Role, dict[str, Scope], int]]:
    roles = (await session.execute(select(Role).order_by(Role.is_system.desc(), Role.name))).scalars().all()
    counts = dict((await session.execute(select(UserRole.role_id, func.count()).group_by(UserRole.role_id))).all())
    return [(r, await role_grants(session, r.id), counts.get(r.id, 0)) for r in roles]


async def get_role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await session.get(Role, role_id)
    if role is None:
        raise NotFound("Role not found")
    return role


async def _replace_grants(session: AsyncSession, role_id: uuid.UUID, grants: dict[str, Scope]) -> None:
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    session.add_all(RolePermission(role_id=role_id, permission=k, scope=v.value) for k, v in grants.items())


async def create_role(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    key: str,
    name: str,
    description: str | None,
    grants: dict[str, str],
) -> Role:
    clean = _validate_grants(grants)
    if (await session.execute(select(Role.id).where(Role.key == key))).first():
        raise Conflict(f"A role with key {key!r} already exists")
    role = Role(key=key, name=name, description=description)
    session.add(role)
    await session.flush()
    await _replace_grants(session, role.id, clean)
    await audit.record(
        session,
        actor_id=actor_id,
        action="role.created",
        entity_type="role",
        entity_id=role.id,
        after={"key": key, "name": name, "grants": clean},
    )
    return role


async def update_role(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    role_id: uuid.UUID,
    name: str | None,
    description: str | None,
    grants: dict[str, str] | None,
) -> Role:
    role = await get_role(session, role_id)
    before = {"name": role.name, "description": role.description, "grants": await role_grants(session, role.id)}
    if grants is not None:
        if role.grants_all:
            raise Forbidden("The Administrator role always has every permission")
        await _replace_grants(session, role.id, _validate_grants(grants))
    if name is not None:
        role.name = name
    if description is not None:
        role.description = description
    await session.flush()
    after = {"name": role.name, "description": role.description, "grants": await role_grants(session, role.id)}
    b, a = audit.diff(before, after)
    await audit.record(
        session, actor_id=actor_id, action="role.updated", entity_type="role", entity_id=role.id, before=b, after=a
    )
    return role


async def delete_role(session: AsyncSession, *, actor_id: uuid.UUID, role_id: uuid.UUID) -> None:
    role = await get_role(session, role_id)
    if role.is_system:
        raise Forbidden("System roles cannot be deleted")
    in_use = (await session.execute(select(func.count()).where(UserRole.role_id == role_id))).scalar_one()
    if in_use:
        raise Conflict(f"Role is assigned to {in_use} user(s); unassign it first")
    await session.delete(role)
    await audit.record(
        session,
        actor_id=actor_id,
        action="role.deleted",
        entity_type="role",
        entity_id=role_id,
        before={"key": role.key, "name": role.name},
    )


async def user_role_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    return list((await session.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))).scalars())


async def roles_by_user(session: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Role]]:
    rows = (
        await session.execute(
            select(UserRole.user_id, Role).join(Role, Role.id == UserRole.role_id).where(UserRole.user_id.in_(user_ids))
        )
    ).all()
    out: dict[uuid.UUID, list[Role]] = {uid: [] for uid in user_ids}
    for uid, role in rows:
        out[uid].append(role)
    return out


async def set_user_roles(
    session: AsyncSession, *, actor_id: uuid.UUID, user_id: uuid.UUID, role_ids: list[uuid.UUID]
) -> None:
    if actor_id == user_id:
        raise Forbidden("You cannot change your own roles")
    role_ids = list(dict.fromkeys(role_ids))
    found = set((await session.execute(select(Role.id).where(Role.id.in_(role_ids)))).scalars())
    missing = [str(r) for r in role_ids if r not in found]
    if missing:
        raise ValidationFailed(
            "Unknown role", errors=[field_error("role_ids", f"Unknown role(s): {', '.join(missing)}")]
        )
    before = sorted(str(r) for r in await user_role_ids(session, user_id))
    await session.execute(delete(UserRole).where(UserRole.user_id == user_id))
    session.add_all(UserRole(user_id=user_id, role_id=r) for r in role_ids)
    await session.flush()
    after = sorted(str(r) for r in role_ids)
    if before != after:
        await audit.record(
            session,
            actor_id=actor_id,
            action="user.roles_changed",
            entity_type="user",
            entity_id=user_id,
            before={"role_ids": before},
            after={"role_ids": after},
        )


async def admin_user_ids(session: AsyncSession) -> set[uuid.UUID]:
    """Users holding a role that grants everything (Administrator)."""
    return set(
        (
            await session.execute(
                select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(Role.grants_all.is_(True))
            )
        ).scalars()
    )


async def assign_roles_system(session: AsyncSession, *, user_id: uuid.UUID, role_ids: list[uuid.UUID]) -> None:
    """Bootstrap/CLI path with no acting user, so no self-assignment check applies."""
    session.add_all(UserRole(user_id=user_id, role_id=r) for r in dict.fromkeys(role_ids))
    await session.flush()


async def seed_default_roles(session: AsyncSession) -> None:
    """Create missing default roles. Existing roles are never overwritten (admins may have edited them)."""
    existing = set((await session.execute(select(Role.key))).scalars())
    for spec in DEFAULT_ROLES:
        if spec["key"] in existing:
            continue
        role = Role(
            key=spec["key"],
            name=spec["name"],
            description=spec["description"],
            is_system=True,
            grants_all=spec.get("grants_all", False),
        )
        session.add(role)
        await session.flush()
        await _replace_grants(session, role.id, _validate_grants({k: v.value for k, v in spec["grants"].items()}))


async def role_by_key(session: AsyncSession, key: str) -> Role:
    role = (await session.execute(select(Role).where(Role.key == key))).scalar_one_or_none()
    if role is None:
        raise NotFound(f"Role {key!r} not found")
    return role
