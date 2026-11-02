"""Backup file format: one zip holding every table's rows (PostgreSQL binary COPY), sequence positions,
attachment files and a manifest. Read and written with asyncpg alone, so no PostgreSQL client tools are
needed on any machine (the Windows dev cluster in tools/devdb has none).

    manifest.json        format, schema revision, per-table column lists and row counts, sequences
    tables/<name>.bin    COPY ... TO STDOUT (FORMAT binary) of the listed columns
    files/<object_key>   attachment blobs

Rows load back only into a database migrated to the same schema revision, so column lists match exactly.
"""

import asyncio
import json
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import asyncpg

FORMAT = "erp-backup"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
# Signed-in sessions and idempotency replays belong to one installation, not to the business data.
SKIPPED_TABLES = frozenset({"alembic_version", "user_sessions", "idempotency_keys"})
CHUNK = 1024 * 1024

_TABLES_SQL = """
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY c.relname
"""
_COLUMNS_SQL = """
SELECT a.attname FROM pg_attribute a
WHERE a.attrelid = ('public.' || quote_ident($1))::regclass
  AND a.attnum > 0 AND NOT a.attisdropped AND a.attgenerated = ''
ORDER BY a.attnum
"""
_SEQUENCES_SQL = "SELECT sequencename, last_value FROM pg_sequences WHERE schemaname = 'public' ORDER BY 1"


class BackupError(Exception):
    """The file is not a usable backup, or does not fit this database."""


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def _columns(conn: asyncpg.Connection, table: str) -> list[str]:
    return [r[0] for r in await conn.fetch(_COLUMNS_SQL, table)]


async def dump(dsn: str, target: Path, *, kind: str, attachments_dir: Path) -> dict[str, Any]:
    """Write a consistent snapshot (one REPEATABLE READ transaction) of the database at `dsn` to `target`."""
    conn = await asyncpg.connect(dsn)
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                schema = await conn.fetchval("SELECT version_num FROM alembic_version")
                tables: dict[str, dict[str, Any]] = {}
                for (name,) in await conn.fetch(_TABLES_SQL):
                    if name in SKIPPED_TABLES:
                        continue
                    columns = await _columns(conn, name)
                    with zf.open(f"tables/{name}.bin", "w", force_zip64=True) as fh:

                        async def write(chunk: bytes, fh: IO[bytes] = fh) -> None:
                            fh.write(chunk)

                        status = await conn.copy_from_table(name, columns=columns, output=write, format="binary")
                    tables[name] = {"columns": columns, "rows": int(status.split()[-1])}
                sequences = {r["sequencename"]: r["last_value"] for r in await conn.fetch(_SEQUENCES_SQL)}
                keys = [r[0] for r in await conn.fetch("SELECT object_key FROM attachments")]

            files = missing = 0
            for key in keys:
                path = attachments_dir / key
                if path.is_file():
                    await asyncio.to_thread(zf.write, path, f"files/{key}")
                    files += 1
                else:
                    missing += 1
            manifest = {
                "format": FORMAT,
                "format_version": FORMAT_VERSION,
                "kind": kind,
                "created_at": datetime.now(UTC).isoformat(),
                "schema": schema,
                "tables": tables,
                "sequences": sequences,
                "files": files,
                "missing_files": missing,
            }
            zf.writestr(MANIFEST, json.dumps(manifest, indent=2))
    finally:
        await conn.close()
    return manifest


def read_manifest(source: Path) -> dict[str, Any]:
    """Validate the archive's structure and return its manifest."""
    try:
        with zipfile.ZipFile(source) as zf:
            names = set(zf.namelist())
            manifest = json.loads(zf.read(MANIFEST))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise BackupError("Not a backup file made by this app") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise BackupError("Not a backup file made by this app")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise BackupError(f"Unsupported backup format version {manifest.get('format_version')!r}")
    tables = manifest.get("tables")
    if not isinstance(tables, dict) or not isinstance(manifest.get("schema"), str):
        raise BackupError("The backup's manifest is incomplete")
    absent = [t for t in tables if f"tables/{t}.bin" not in names]
    if absent:
        raise BackupError(f"The backup is missing data for: {', '.join(sorted(absent))}")
    return manifest


async def _chunks(fh: IO[bytes]) -> AsyncIterator[bytes]:
    while chunk := fh.read(CHUNK):
        yield chunk


async def load(dsn: str, source: Path) -> None:
    """Replace every row of the database at `dsn`, which must be migrated to the backup's schema revision."""
    manifest = read_manifest(source)
    conn = await asyncpg.connect(dsn)
    try:
        with zipfile.ZipFile(source) as zf:
            async with conn.transaction():
                # Rows were consistent when dumped: load them without triggers or FK checks (needs a superuser).
                await conn.execute("SET LOCAL session_replication_role = replica")
                present = {r[0] for r in await conn.fetch(_TABLES_SQL)} - {"alembic_version"}
                for name, info in manifest["tables"].items():
                    if name not in present:
                        raise BackupError(f"Table {name} does not exist in this schema version")
                    if await _columns(conn, name) != info["columns"]:
                        raise BackupError(f"Columns of table {name} do not match this schema version")
                await conn.execute("TRUNCATE " + ", ".join(_ident(t) for t in sorted(present)))
                for name, info in manifest["tables"].items():
                    with zf.open(f"tables/{name}.bin") as fh:
                        await conn.copy_to_table(name, source=_chunks(fh), columns=info["columns"], format="binary")
                existing = {r[0] for r in await conn.fetch(_SEQUENCES_SQL)}
                for seq, value in manifest.get("sequences", {}).items():
                    if seq in existing:
                        await conn.execute(
                            "SELECT setval(('public.' || quote_ident($1))::regclass, $2, $3)",
                            seq,
                            value if value is not None else 1,
                            value is not None,
                        )
    finally:
        await conn.close()


def extract_files(source: Path, attachments_dir: Path) -> int:
    """Copy the archive's attachment blobs into `attachments_dir`; paths may not escape it."""
    base = attachments_dir.resolve()
    count = 0
    with zipfile.ZipFile(source) as zf:
        for info in zf.infolist():
            if not info.filename.startswith("files/") or info.is_dir():
                continue
            target = (base / info.filename.removeprefix("files/")).resolve()
            if base not in target.parents:
                raise BackupError(f"Unsafe file path in backup: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                while chunk := src.read(CHUNK):
                    dst.write(chunk)
            count += 1
    return count
