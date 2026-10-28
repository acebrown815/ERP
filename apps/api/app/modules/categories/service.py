import uuid
from typing import Any

from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base
from app.core.errors import Conflict, Forbidden, NotFound, PreconditionFailed, ValidationFailed, field_error
from app.modules.audit import api as audit
from app.modules.categories.groups import (
    BOOL,
    GROUPS,
    OTHER,
    STR,
    STR_LIST,
    UUID_STR,
    CategoryGroup,
    system_value,
)
from app.modules.categories.models import Category

MAX_DEPTH = 5


def get_group(group_key: str) -> CategoryGroup:
    group = GROUPS.get(group_key)
    if group is None:
        raise ValidationFailed(
            "Unknown category group", errors=[field_error("group_key", f"Unknown group {group_key!r}", "unknown_group")]
        )
    return group


def _snapshot(c: Category) -> dict[str, Any]:
    return {
        "group_key": c.group_key,
        "name": c.name,
        "parent_id": c.parent_id,
        "description": c.description,
        "config": c.config,
        "is_active": c.is_active,
        "sort_order": c.sort_order,
        "merged_into_id": c.merged_into_id,
    }


def _validate_config(group: CategoryGroup, config: dict[str, Any]) -> dict[str, Any]:
    errors = []
    for key, value in config.items():
        kind = group.config_schema.get(key)
        if kind is None:
            errors.append(field_error(f"config.{key}", f"Not a setting of {group.label}", "unknown_key"))
            continue
        ok = {
            BOOL: isinstance(value, bool),
            STR: isinstance(value, str),
            STR_LIST: isinstance(value, list) and all(isinstance(v, str) for v in value),
        }.get(kind)
        if kind == UUID_STR:
            try:
                uuid.UUID(str(value))
                ok = True
            except ValueError:
                ok = False
        if not ok:
            errors.append(field_error(f"config.{key}", f"Expected {kind}", "invalid_type"))
    if errors:
        raise ValidationFailed("Invalid category settings", errors=errors)
    return config


async def get(session: AsyncSession, category_id: uuid.UUID, *, lock: bool = False) -> Category:
    stmt = select(Category).where(Category.id == category_id)
    if lock:
        stmt = stmt.with_for_update()
    category = (await session.execute(stmt)).scalar_one_or_none()
    if category is None:
        raise NotFound("Category not found")
    return category


async def list_categories(
    session: AsyncSession, *, group_key: str | None, include_inactive: bool, q: str | None
) -> list[Category]:
    stmt = select(Category).order_by(Category.group_key, Category.sort_order, func.lower(Category.name))
    if group_key:
        get_group(group_key)
        stmt = stmt.where(Category.group_key == group_key)
    if not include_inactive:
        stmt = stmt.where(Category.is_active.is_(True))
    if q:
        stmt = stmt.where(Category.name.ilike(f"%{q.strip()}%"))
    return list((await session.execute(stmt)).scalars())


async def paths(session: AsyncSession, categories: list[Category]) -> dict[uuid.UUID, str]:
    """'Other › Wise Transfer' style display paths."""
    groups = {c.group_key for c in categories}
    if not groups:
        return {}
    all_rows = (await session.execute(select(Category).where(Category.group_key.in_(groups)))).scalars().all()
    by_id = {c.id: c for c in all_rows}

    def path(c: Category) -> str:
        names, cur, guard = [], c, 0
        while cur is not None and guard <= MAX_DEPTH + 1:
            names.append(cur.name)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
            guard += 1
        return " › ".join(reversed(names))

    return {c.id: path(c) for c in categories}


async def _depth_and_ancestors(session: AsyncSession, parent_id: uuid.UUID | None) -> tuple[int, set[uuid.UUID]]:
    depth, ancestors, cur = 0, set(), parent_id
    while cur is not None:
        if cur in ancestors:
            break
        ancestors.add(cur)
        depth += 1
        cur = (await session.execute(select(Category.parent_id).where(Category.id == cur))).scalar_one_or_none()
    return depth, ancestors


async def _check_parent(
    session: AsyncSession, group_key: str, parent_id: uuid.UUID | None, moving_id: uuid.UUID | None = None
) -> None:
    if parent_id is None:
        return
    parent = await session.get(Category, parent_id)
    if parent is None or parent.group_key != group_key:
        raise ValidationFailed("Invalid parent", errors=[field_error("parent_id", "Parent must be in the same group")])
    if parent.merged_into_id or not parent.is_active:
        raise ValidationFailed(
            "Invalid parent", errors=[field_error("parent_id", "Parent must be active and not merged")]
        )
    depth, ancestors = await _depth_and_ancestors(session, parent_id)
    if moving_id is not None and moving_id in ancestors:
        raise ValidationFailed(
            "Invalid parent", errors=[field_error("parent_id", "A category cannot be moved under its own child")]
        )
    if depth >= MAX_DEPTH:
        raise ValidationFailed("Too deep", errors=[field_error("parent_id", f"At most {MAX_DEPTH} levels")])


async def _flush_unique(session: AsyncSession) -> None:
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        if "uq_categories_sibling_name" in str(exc.orig):
            raise ValidationFailed(
                "Name already used",
                errors=[field_error("name", "A category with this name already exists here", "duplicate")],
            ) from exc
        raise


async def create(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    group_key: str,
    name: str,
    parent_id: uuid.UUID | None = None,
    description: str | None = None,
    config: dict[str, Any] | None = None,
    sort_order: int | None = None,
) -> Category:
    group = get_group(group_key)
    await _check_parent(session, group_key, parent_id)
    if sort_order is None:
        current_max = (
            await session.execute(
                select(func.max(Category.sort_order)).where(
                    Category.group_key == group_key, Category.parent_id.is_not_distinct_from(parent_id)
                )
            )
        ).scalar_one()
        sort_order = (current_max or 0) + 10
    category = Category(
        group_key=group_key,
        name=name.strip(),
        parent_id=parent_id,
        description=description,
        config=_validate_config(group, config or {}),
        sort_order=sort_order,
        created_by=actor_id,
        updated_by=actor_id,
    )
    session.add(category)
    await _flush_unique(session)
    await audit.record(
        session,
        actor_id=actor_id,
        action="category.created",
        entity_type="category",
        entity_id=category.id,
        after=_snapshot(category),
    )
    return category


async def update_category(
    session: AsyncSession, *, actor_id: uuid.UUID, category_id: uuid.UUID, version: int, changes: dict[str, Any]
) -> Category:
    category = await get(session, category_id, lock=True)
    if category.version != version:
        raise PreconditionFailed()
    if category.merged_into_id:
        raise Conflict("A merged category cannot be edited; unmerge it first")
    group = get_group(category.group_key)
    before = _snapshot(category)

    if "parent_id" in changes and changes["parent_id"] != category.parent_id:
        if category.is_system:
            raise Forbidden("System categories stay at the top level")
        await _check_parent(session, category.group_key, changes["parent_id"], moving_id=category.id)
        category.parent_id = changes["parent_id"]
    if "name" in changes:
        category.name = changes["name"].strip()
    if "description" in changes:
        category.description = changes["description"]
    if "sort_order" in changes:
        category.sort_order = changes["sort_order"]
    if "config" in changes:
        category.config = _validate_config(group, changes["config"] or {})

    category.version += 1
    category.updated_by = actor_id
    await _flush_unique(session)
    b, a = audit.diff(before, _snapshot(category))
    if a:
        await audit.record(
            session,
            actor_id=actor_id,
            action="category.updated",
            entity_type="category",
            entity_id=category.id,
            before=b,
            after=a,
        )
    return category


async def set_active(session: AsyncSession, *, actor_id: uuid.UUID, category_id: uuid.UUID, active: bool) -> Category:
    category = await get(session, category_id, lock=True)
    if category.is_active == active:
        return category
    if category.merged_into_id:
        raise Conflict("A merged category stays inactive; unmerge it to reactivate")
    if not active:
        sv = system_value(category.group_key, category.system_key) if category.system_key else None
        if sv and sv.protected:
            raise Forbidden(f"'{category.name}' is required by the system and cannot be deactivated")
        has_active_children = (
            await session.execute(
                select(exists().where(Category.parent_id == category.id, Category.is_active.is_(True)))
            )
        ).scalar_one()
        if has_active_children:
            raise Conflict("Deactivate or move its sub-categories first")
    elif category.parent_id:
        parent = await session.get(Category, category.parent_id)
        if parent is not None and not parent.is_active:
            raise Conflict("Activate the parent category first")

    category.is_active = active
    category.version += 1
    category.updated_by = actor_id
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="category.activated" if active else "category.deactivated",
        entity_type="category",
        entity_id=category.id,
    )
    return category


async def merge(session: AsyncSession, *, actor_id: uuid.UUID, source_id: uuid.UUID, target_id: uuid.UUID) -> Category:
    """Merge `source` into `target`. Historical records keep pointing at `source`; reports group it
    under `target` via canonical_id(). Nothing historical is rewritten."""
    if source_id == target_id:
        raise ValidationFailed("Cannot merge into itself", errors=[field_error("target_id", "Choose another category")])
    source = await get(session, source_id, lock=True)
    target = await get(session, target_id, lock=True)
    if source.group_key != target.group_key:
        raise ValidationFailed("Different groups", errors=[field_error("target_id", "Must be in the same group")])
    if source.is_system:
        raise Forbidden("System categories cannot be merged away")
    if source.merged_into_id:
        raise Conflict("Category is already merged")
    if target.merged_into_id or not target.is_active:
        raise ValidationFailed("Invalid target", errors=[field_error("target_id", "Target must be active")])
    _, target_ancestors = await _depth_and_ancestors(session, target.parent_id)
    if source.id in target_ancestors:
        raise ValidationFailed("Invalid target", errors=[field_error("target_id", "Target is inside the source")])
    has_children = (
        await session.execute(
            select(exists().where(Category.parent_id == source.id, Category.merged_into_id.is_(None)))
        )
    ).scalar_one()
    if has_children:
        raise Conflict("Move or merge its sub-categories first")

    # Keep merge chains one level deep: anything already merged into the source now points at the target.
    await session.execute(update(Category).where(Category.merged_into_id == source.id).values(merged_into_id=target.id))
    source.merged_into_id = target.id
    source.is_active = False
    source.version += 1
    source.updated_by = actor_id
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="category.merged",
        entity_type="category",
        entity_id=source.id,
        after={"merged_into_id": target.id, "target_name": target.name},
    )
    return source


async def unmerge(session: AsyncSession, *, actor_id: uuid.UUID, category_id: uuid.UUID) -> Category:
    category = await get(session, category_id, lock=True)
    if category.merged_into_id is None:
        raise Conflict("Category is not merged")
    previous = category.merged_into_id
    category.merged_into_id = None
    category.is_active = True
    category.version += 1
    category.updated_by = actor_id
    await _flush_unique(session)
    await audit.record(
        session,
        actor_id=actor_id,
        action="category.unmerged",
        entity_type="category",
        entity_id=category.id,
        before={"merged_into_id": previous},
    )
    return category


async def _reference_count(session: AsyncSession, category_id: uuid.UUID) -> int:
    """Rows in any table that reference this category through a foreign key."""
    total = 0
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.column.table.name == "categories" and fk.column.name == "id":
                total += (
                    await session.execute(select(func.count()).select_from(table).where(fk.parent == category_id))
                ).scalar_one()
    return total


async def delete(session: AsyncSession, *, actor_id: uuid.UUID, category_id: uuid.UUID) -> None:
    category = await get(session, category_id, lock=True)
    if category.is_system:
        raise Forbidden("System categories cannot be deleted")
    refs = await _reference_count(session, category.id)
    if refs:
        raise Conflict(f"Category is used by {refs} record(s). Deactivate or merge it instead.")
    snapshot = _snapshot(category)
    await session.delete(category)
    await session.flush()
    await audit.record(
        session,
        actor_id=actor_id,
        action="category.deleted",
        entity_type="category",
        entity_id=category_id,
        before=snapshot,
    )


async def canonical_id(session: AsyncSession, category_id: uuid.UUID) -> uuid.UUID:
    merged = (await session.execute(select(Category.merged_into_id).where(Category.id == category_id))).scalar_one()
    return merged or category_id


async def by_system_key(session: AsyncSession, group_key: str, system_key: str) -> Category:
    category = (
        await session.execute(
            select(Category).where(Category.group_key == group_key, Category.system_key == system_key)
        )
    ).scalar_one_or_none()
    if category is None:
        raise NotFound(f"System category {group_key}.{system_key} is missing; run the seed command")
    return category


async def validate_choice(
    session: AsyncSession,
    *,
    group_key: str,
    category_id: uuid.UUID | None,
    other_text: str | None,
    field: str = "category_id",
    other_field: str = "other_text",
) -> Category:
    """Shared rule for every form with a category picker (docs/architecture.md, Section 12.2):
    a category from the right group is required; choosing the group's 'Other' requires a description;
    'Other' never bypasses the module's own accounting validation."""
    if category_id is None:
        raise ValidationFailed("Category required", errors=[field_error(field, "Choose a category", "required")])
    category = await session.get(Category, category_id)
    if category is None or category.group_key != group_key:
        raise ValidationFailed("Invalid category", errors=[field_error(field, f"Must be a {group_key} category")])
    if not category.is_active:
        raise ValidationFailed("Inactive category", errors=[field_error(field, "This category is no longer active")])
    if category.system_key == OTHER and not (other_text or "").strip():
        raise ValidationFailed(
            "Description required", errors=[field_error(other_field, "Describe what 'Other' means here", "required")]
        )
    return category


async def seed(session: AsyncSession) -> int:
    """Insert missing system values. Existing rows (possibly renamed by admins) are left alone."""
    existing = {(g, k) for g, k in (await session.execute(select(Category.group_key, Category.system_key)))}
    created = 0
    for group in GROUPS.values():
        for order, value in enumerate(group.values, start=1):
            if (group.key, value.key) in existing:
                continue
            session.add(
                Category(
                    group_key=group.key,
                    system_key=value.key,
                    name=value.name,
                    config=dict(value.config),
                    is_system=True,
                    sort_order=order * 10,
                )
            )
            created += 1
    await session.flush()
    return created


async def set_config_default(session: AsyncSession, group_key: str, system_key: str, key: str, value: Any) -> None:
    """Seed helper: set a config key on a system category unless an admin already set it."""
    category = await by_system_key(session, group_key, system_key)
    if key not in category.config:
        category.config = {**category.config, key: value}
        await session.flush()


async def find(session: AsyncSession, group_key: str, value: str) -> Category | None:
    """Match an active category by system key or (case-insensitive) name, e.g. for CSV imports."""
    value = value.strip()
    if not value:
        return None
    return (
        await session.execute(
            select(Category)
            .where(
                Category.group_key == group_key,
                Category.is_active.is_(True),
                (Category.system_key == value.lower().replace(" ", "_")) | (func.lower(Category.name) == value.lower()),
            )
            .order_by(Category.is_system.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
