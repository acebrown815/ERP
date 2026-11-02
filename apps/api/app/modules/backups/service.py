"""Backups and restore from the app (Settings → Backups).

Backup files live in `settings.backups_dir` (archive.py describes the format). Creating one and restoring
one run as background jobs; `job.json` in the same directory records the latest job so the page can follow
it, and a lock file keeps the API and the worker's nightly backup from running two jobs at once.

Restore never touches the live database until the backup has been loaded and verified elsewhere:
  1. safety backup of the current data ("pre-restore")
  2. load the file into a scratch database `<db>_incoming` migrated to the backup's schema revision
  3. migrate it to the current revision and run the consistency checks
  4. swap: block connections to `<db>`, rename it away, rename the scratch database into place, drop the old one
Everyone is signed out, because sessions are not part of a backup.
"""

import asyncio
import json
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import structlog
from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import checks
from app.core.config import get_settings
from app.core.db import engine
from app.core.errors import Conflict, NotFound, ValidationFailed, field_error
from app.modules.audit import api as audit
from app.modules.backups import archive

log = structlog.get_logger()

Kind = Literal["auto", "manual", "upload", "pre-restore"]
NAME_RE = re.compile(r"^erp-backup-\d{8}T\d{6}Z-(auto|manual|upload|pre-restore)(?:-\d+)?\.zip$")
JOB_FILE = "job.json"
LOCK_FILE = ".lock"
LOCK_STALE_SECONDS = 6 * 3600
# An older backup can hold outbox events that look stale; the worker processes them after the restore.
NON_BLOCKING_CHECKS = frozenset({"worker"})
API_DIR = Path(__file__).resolve().parents[3]

_tasks: set[asyncio.Task[None]] = set()  # keep running jobs referenced


@dataclass
class BackupInfo:
    name: str
    kind: str
    created_at: datetime
    size: int
    schema_version: str
    rows: int
    files: int


@dataclass
class Job:
    kind: Literal["backup", "restore"]
    state: Literal["running", "succeeded", "failed"]
    started_at: str
    by: str | None = None
    file: str | None = None
    finished_at: str | None = None
    message: str | None = None


# ---- paths, urls, lock, job state ----------------------------------------------------------------


def backups_dir() -> Path:
    path = Path(get_settings().backups_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _attachments_dir() -> Path:
    return Path(get_settings().attachments_dir).resolve()


def _url(database: str | None = None) -> URL:
    url = make_url(get_settings().database_url)
    return url.set(database=database) if database else url


def _dsn(database: str | None = None) -> str:
    return _url(database).set(drivername="postgresql").render_as_string(hide_password=False)


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@contextmanager
def _locked() -> Iterator[None]:
    path = backups_dir() / LOCK_FILE
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.time() - path.stat().st_mtime > LOCK_STALE_SECONDS:
                path.unlink(missing_ok=True)  # left behind by a process that died mid-job
                continue
            raise Conflict("Another backup or restore is running. Try again when it has finished.") from None
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        break
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def read_job() -> Job | None:
    try:
        return Job(**json.loads((backups_dir() / JOB_FILE).read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError, TypeError):
        return None


def _write_job(job: Job) -> None:
    path = backups_dir() / JOB_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(job)), encoding="utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---- files -----------------------------------------------------------------------------------------


def path_of(name: str) -> Path:
    path = backups_dir() / name
    if not NAME_RE.match(name) or not path.is_file():
        raise NotFound("Backup not found")
    return path


def _info(path: Path, manifest: dict[str, Any]) -> BackupInfo:
    match = NAME_RE.match(path.name)
    return BackupInfo(
        name=path.name,
        kind=match.group(1) if match else manifest.get("kind", "manual"),
        created_at=datetime.fromisoformat(manifest["created_at"]),
        size=path.stat().st_size,
        schema_version=manifest["schema"],
        rows=sum(t["rows"] for t in manifest["tables"].values()),
        files=manifest.get("files", 0),
    )


def list_backups() -> list[BackupInfo]:
    out = []
    for path in backups_dir().iterdir():
        if not NAME_RE.match(path.name):
            continue
        try:
            out.append(_info(path, archive.read_manifest(path)))
        except (archive.BackupError, KeyError, ValueError):
            log.warning("backup.unreadable", file=path.name)
    return sorted(out, key=lambda b: b.created_at, reverse=True)


def _new_path(kind: Kind) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = backups_dir()
    path, n = base / f"erp-backup-{stamp}-{kind}.zip", 1
    while path.exists():
        n += 1
        path = base / f"erp-backup-{stamp}-{kind}-{n}.zip"
    return path


async def _create(kind: Kind) -> BackupInfo:
    path = _new_path(kind)
    part = path.with_suffix(".part")
    try:
        manifest = await archive.dump(_dsn(), part, kind=kind, attachments_dir=_attachments_dir())
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
    info = _info(path, manifest)
    log.info("backup.created", file=info.name, rows=info.rows, files=info.files, size=info.size)
    return info


async def save_upload(upload: UploadFile) -> BackupInfo:
    limit = get_settings().backups_max_upload_bytes
    path = _new_path("upload")
    part = path.with_suffix(".part")
    size = 0
    try:
        with part.open("wb") as fh:
            while chunk := await upload.read(archive.CHUNK):
                size += len(chunk)
                if size > limit:
                    raise ValidationFailed(
                        "File too large", errors=[field_error("file", f"Maximum size is {limit // 1024**2} MB")]
                    )
                fh.write(chunk)
        try:
            manifest = archive.read_manifest(part)
        except archive.BackupError as exc:
            raise ValidationFailed(str(exc), errors=[field_error("file", str(exc))]) from exc
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
    return _info(path, manifest)


def delete(name: str) -> None:
    path_of(name).unlink()


def prune(keep_days: int) -> int:
    """Delete nightly backups older than `keep_days`. Manual, uploaded and pre-restore backups are kept."""
    cutoff = datetime.now(UTC) - timedelta(days=keep_days)
    removed = 0
    for info in list_backups():
        if info.kind == "auto" and info.created_at < cutoff:
            (backups_dir() / info.name).unlink(missing_ok=True)
            removed += 1
    return removed


# ---- jobs ------------------------------------------------------------------------------------------


def _start(job: Job, work: Any) -> Job:
    """Run `work()` in the background under the lock; the lock is taken before returning."""
    lock = _locked()
    lock.__enter__()
    _write_job(job)

    async def run() -> None:
        try:
            job.message = await work()
            job.state = "succeeded"
        except Exception as exc:
            log.exception(f"backup.{job.kind}_failed", file=job.file)
            job.state = "failed"
            job.message = str(exc) if isinstance(exc, archive.BackupError | RestoreError) else f"Failed: {exc}"
        finally:
            job.finished_at = _now()
            _write_job(job)
            lock.__exit__(None, None, None)

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job


def start_backup(*, by: str) -> Job:
    job = Job(kind="backup", state="running", started_at=_now(), by=by)

    async def work() -> str:
        info = await _create("manual")
        job.file = info.name
        return f"Created {info.name}"

    return _start(job, work)


async def nightly() -> BackupInfo | None:
    """Worker: one automatic backup a day, then remove old automatic ones. Skipped while a job runs."""
    try:
        with _locked():
            info = await _create("auto")
    except Conflict:
        log.info("backup.nightly_skipped", reason="another job is running")
        return None
    prune(get_settings().backups_keep_days)
    return info


class RestoreError(Exception):
    pass


def _alembic_config(url: URL) -> Any:
    from alembic.config import Config

    cfg = Config()  # no ini file: keep the running process's logging configuration
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.attributes["database_url"] = url.render_as_string(hide_password=False)
    return cfg


def _known_revision(revision: str) -> bool:
    from alembic.script import ScriptDirectory

    try:
        return ScriptDirectory.from_config(_alembic_config(_url())).get_revision(revision) is not None
    except Exception:
        return False


def _upgrade(url: URL, revision: str) -> None:
    from alembic import command

    command.upgrade(_alembic_config(url), revision)


def start_restore(name: str, *, user_id: Any, by: str) -> Job:
    path = path_of(name)
    try:
        manifest = archive.read_manifest(path)
    except archive.BackupError as exc:
        raise ValidationFailed(str(exc)) from exc
    if not _known_revision(manifest["schema"]):
        raise ValidationFailed(
            f"This backup is from a newer version of the app (schema {manifest['schema']}). Upgrade first."
        )
    job = Job(kind="restore", state="running", started_at=_now(), by=by, file=name)

    async def work() -> str:
        safety = await _restore(path, manifest, user_id=user_id, by=by)
        return f"Restored {name}. The data before the restore was saved as {safety}. Everyone was signed out."

    return _start(job, work)


async def _restore(path: Path, manifest: dict[str, Any], *, user_id: Any, by: str) -> str:
    live = _url().database
    assert live
    incoming, previous = f"{live}_incoming", f"{live}_previous"
    safety = await _create("pre-restore")

    admin = create_async_engine(_url("postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as c:
            await c.execute(text(f"DROP DATABASE IF EXISTS {_ident(incoming)} WITH (FORCE)"))
            await c.execute(text(f"CREATE DATABASE {_ident(incoming)}"))
        try:
            await asyncio.to_thread(_upgrade, _url(incoming), manifest["schema"])
            await archive.load(_dsn(incoming), path)
            await asyncio.to_thread(_upgrade, _url(incoming), "head")
            await _verify_and_record(incoming, path.name, manifest, safety.name, user_id=user_id, by=by)
            await asyncio.to_thread(archive.extract_files, path, _attachments_dir())
            await _swap(admin, live, incoming, previous)
        except BaseException:
            async with admin.connect() as c:
                await c.execute(text(f"DROP DATABASE IF EXISTS {_ident(incoming)} WITH (FORCE)"))
            raise
    finally:
        await admin.dispose()
    log.info("backup.restored", file=path.name, safety=safety.name, by=by)
    return safety.name


async def _verify_and_record(
    database: str, name: str, manifest: dict[str, Any], safety: str, *, user_id: Any, by: str
) -> None:
    scratch = create_async_engine(_url(database), poolclass=NullPool)
    try:
        async with async_sessionmaker(scratch, expire_on_commit=False)() as session:
            results = await checks.run_all(session)
            failed = [r for r in results if not r.ok and r.key not in NON_BLOCKING_CHECKS]
            if failed:
                raise RestoreError(
                    "The backup failed the consistency checks, so nothing was changed: "
                    + "; ".join(f"{r.label}: {r.detail}" for r in failed)
                )
            known = (await session.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id})).first()
            await audit.record(
                session,
                actor_id=user_id if known else None,
                action="backup.restored",
                entity_type="backup",
                entity_id=name,
                after={"file": name, "backup_created_at": manifest["created_at"], "safety_backup": safety, "by": by},
            )
            await session.commit()
    finally:
        await scratch.dispose()


async def _rename(conn: Any, database: str, new_name: str) -> None:
    """Rename once the database's remaining connections are gone; terminated backends take a moment to exit."""
    terminate = "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :d AND pid <> pg_backend_pid()"
    for attempt in range(50):
        await conn.execute(text(terminate), {"d": database})
        try:
            await conn.execute(text(f"ALTER DATABASE {_ident(database)} RENAME TO {_ident(new_name)}"))
            return
        except DBAPIError:
            if attempt == 49:
                raise
            await asyncio.sleep(0.2)


async def _swap(admin: AsyncEngine, live: str, incoming: str, previous: str) -> None:
    await engine.dispose()  # this process's pooled connections to the live database
    async with admin.connect() as c:
        await c.execute(text(f"DROP DATABASE IF EXISTS {_ident(previous)} WITH (FORCE)"))
        await c.execute(text(f"ALTER DATABASE {_ident(live)} WITH ALLOW_CONNECTIONS false"))
        try:
            await _rename(c, live, previous)
        except BaseException:
            await c.execute(text(f"ALTER DATABASE {_ident(live)} WITH ALLOW_CONNECTIONS true"))
            raise
        try:
            await _rename(c, incoming, live)
        except BaseException:
            await _rename(c, previous, live)
            await c.execute(text(f"ALTER DATABASE {_ident(live)} WITH ALLOW_CONNECTIONS true"))
            raise
        await c.execute(text(f"DROP DATABASE {_ident(previous)} WITH (FORCE)"))
