"""Loads and saves the bidding connection settings (one row). Configuration only; nothing read from the sheets
is stored. The secret and token never leave the API and never go into the audit log."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PreconditionFailed, ValidationFailed, field_error
from app.modules.audit import api as audit
from app.modules.bidding.config import (
    DEFAULT_JOB_TABS,
    SECRET_FIELDS,
    TEXT_FIELDS,
    URL_SECRET_FIELDS,
    SourceConfig,
    check_url,
    tab_names,
)
from app.modules.bidding.models import BiddingSettings


async def _row(session: AsyncSession) -> BiddingSettings | None:
    return (await session.execute(select(BiddingSettings))).scalar_one_or_none()


async def load(session: AsyncSession) -> SourceConfig:
    row = await _row(session)
    if row is None:
        return SourceConfig(jobs_tabs=DEFAULT_JOB_TABS)
    return SourceConfig(
        bids_url=(row.bids_webapp_url or "").strip(),
        bids_secret=(row.bids_secret or "").strip(),
        jobs_url=(row.jobs_webapp_url or "").strip(),
        jobs_token=(row.jobs_token or "").strip(),
        jobs_tabs=tuple(tab_names(row.jobs_tabs)) or DEFAULT_JOB_TABS,
        cache_seconds=row.cache_seconds or SourceConfig.cache_seconds,
    )


async def update(
    session: AsyncSession, *, actor_id: uuid.UUID, version: int, changes: dict[str, Any]
) -> BiddingSettings:
    """`changes` holds only fields to change. A secret set to "" is removed; omitting it keeps it."""
    row = await _row(session)
    if row is None:
        row = BiddingSettings(created_by=actor_id, updated_by=actor_id, version=0)
        session.add(row)
        await session.flush()
    if row.version != version:
        raise PreconditionFailed()

    clean: dict[str, Any] = {}
    for name in TEXT_FIELDS:
        if name in changes:
            value = (changes[name] or "").strip()
            if name == "jobs_tabs":
                value = ", ".join(tab_names(value))
            clean[name] = value or None
    if "cache_seconds" in changes:
        clean["cache_seconds"] = changes["cache_seconds"]

    errors = [e for e in (check_url(clean.get(f) or "", f) for f in ("bids_webapp_url", "jobs_webapp_url")) if e]
    if clean.get("cache_seconds") is not None and not 30 <= clean["cache_seconds"] <= 3600:
        errors.append(field_error("cache_seconds", "Between 30 seconds and 1 hour"))
    # The saved secret goes to the saved URL on every read, so a new URL has to come with the secret meant for it.
    for url_field, secret_field in URL_SECRET_FIELDS:
        new_url = clean.get(url_field)
        if new_url and new_url != getattr(row, url_field) and getattr(row, secret_field) and secret_field not in clean:
            errors.append(field_error(secret_field, "Enter the secret again: the URL changed"))
    if errors:
        raise ValidationFailed("Invalid bidding settings", errors=errors)

    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for name, value in clean.items():
        old = getattr(row, name)
        if old == value:
            continue
        if name in SECRET_FIELDS:  # never write secrets to the audit log
            before[name] = "set" if old else None
            after[name] = "changed" if value else None
        else:
            before[name], after[name] = old, value
        setattr(row, name, value)
    if after:
        row.version += 1
        row.updated_by = actor_id
        await session.flush()
        await audit.record(
            session,
            actor_id=actor_id,
            action="bidding_settings.updated",
            entity_type="bidding_settings",
            entity_id=row.id,
            before=before,
            after=after,
        )
    return row


async def current_version(session: AsyncSession) -> int:
    row = await _row(session)
    return row.version if row else 0
