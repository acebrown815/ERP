import asyncio
import io
import shutil
import uuid
import zipfile

import httpx
import pytest
from sqlalchemy import text

from app.core.db import SessionLocal
from app.modules.backups import service
from tests import factories
from tests.conftest import PASSWORD, ClientFactory, login, new_client

B = "/api/v1/backups"


@pytest.fixture(autouse=True)
def empty_backups_dir() -> None:
    shutil.rmtree(service.backups_dir())


async def wait_for_job(c: httpx.AsyncClient) -> dict:
    for _ in range(600):
        job = (await c.get(f"{B}/job")).json()
        if job["state"] != "running":
            return job
        await asyncio.sleep(0.1)
    raise AssertionError("job did not finish")


async def make_backup(c: httpx.AsyncClient) -> str:
    started = await c.post(B)
    assert started.status_code == 202, started.text
    job = await wait_for_job(c)
    assert job["state"] == "succeeded", job
    return job["file"]


async def scalar(sql: str) -> object:
    async with SessionLocal() as s:
        return (await s.execute(text(sql))).scalar_one()


async def receipt(c: httpx.AsyncClient, party_id: str, amount: str) -> None:
    body = await factories.receipt_body(party_id=party_id, amount=amount)
    created = await c.post("/api/v1/payment-entries", json=body)
    assert created.status_code == 201, created.text
    submitted = await c.post(
        f"/api/v1/payment-entries/{created.json()['id']}/submit", headers={"Idempotency-Key": uuid.uuid4().hex}
    )
    assert submitted.status_code == 200, submitted.text


async def test_only_administrators_manage_backups(client_as: ClientFactory) -> None:
    fm = await client_as("finance_manager")
    assert (await fm.get(B)).status_code == 403
    assert (await fm.post(B)).status_code == 403


async def test_backup_lists_and_downloads(admin) -> None:  # type: ignore[no-untyped-def]
    await factories.customer("Kept Customer")
    name = await make_backup(admin)

    listing = (await admin.get(B)).json()
    assert [b["name"] for b in listing["items"]] == [name]
    item = listing["items"][0]
    assert item["kind"] == "manual" and item["rows"] > 0 and item["schema_version"]

    res = await admin.get(f"{B}/{name}/download")
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        names = zf.namelist()
    assert "manifest.json" in names and "tables/parties.bin" in names
    assert "tables/user_sessions.bin" not in names  # sessions are not business data

    logs = (await admin.get("/api/v1/audit-logs", params={"action": "backup."})).json()["items"]
    assert {"backup.started", "backup.downloaded"} <= {e["action"] for e in logs}


async def test_restore_brings_back_the_backed_up_data(admin, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    admin_email = (await admin.get("/api/v1/auth/me")).json()["email"]
    fm = await client_as("finance_manager")
    customer = await factories.customer("Before Backup")
    await receipt(fm, customer, "1000.00")
    name = await make_backup(admin)
    lines_at_backup = await scalar("SELECT count(*) FROM journal_lines")

    # Changes after the backup: these must disappear.
    await factories.customer("After Backup")
    await receipt(fm, customer, "250.00")
    assert await scalar("SELECT count(*) FROM journal_lines") > lines_at_backup

    started = await admin.post(f"{B}/{name}/restore", json={"password": PASSWORD})
    assert started.status_code == 202, started.text
    # Wait on the job itself: a request in flight during the database swap loses its connection (by design).
    await asyncio.gather(*service._tasks)
    # The admin's session did not survive the restore: sessions are not in backups.
    assert (await admin.get("/api/v1/auth/me")).status_code == 401
    reader = new_client()
    assert (await login(reader, admin_email)).status_code == 200
    job = await wait_for_job(reader)
    assert job["state"] == "succeeded", job
    assert "pre-restore" in job["message"]

    assert await scalar("SELECT count(*) FROM parties WHERE name = 'After Backup'") == 0
    assert await scalar("SELECT count(*) FROM parties WHERE name = 'Before Backup'") == 1
    assert await scalar("SELECT count(*) FROM journal_lines") == lines_at_backup
    assert await scalar("SELECT count(*) FROM user_sessions") <= 1  # only the re-login above

    checks = (await reader.get("/api/v1/system/checks")).json()
    assert all(c["ok"] for c in checks["checks"] if c["key"] != "worker"), checks
    restored = (await reader.get("/api/v1/audit-logs", params={"action": "backup.restored"})).json()["items"]
    assert len(restored) == 1 and restored[0]["after"]["file"] == name

    kinds = {b["kind"] for b in (await reader.get(B)).json()["items"]}
    assert kinds == {"manual", "pre-restore"}

    # New rows still get fresh ids after the restore (sequences carried over).
    await factories.customer("After Restore")
    assert (await reader.get("/api/v1/audit-logs/verify")).json()["ok"] is True


async def test_restore_needs_the_password(admin) -> None:  # type: ignore[no-untyped-def]
    name = await make_backup(admin)
    res = await admin.post(f"{B}/{name}/restore", json={"password": "not-my-password"})
    assert res.status_code == 422
    assert res.json()["errors"][0]["field"] == "password"


async def test_upload_accepts_backups_and_rejects_other_files(admin) -> None:  # type: ignore[no-untyped-def]
    name = await make_backup(admin)
    content = (await admin.get(f"{B}/{name}/download")).content

    ok = await admin.post(f"{B}/upload", files={"file": ("from-elsewhere.zip", content, "application/zip")})
    assert ok.status_code == 201, ok.text
    assert ok.json()["kind"] == "upload"

    bad = await admin.post(f"{B}/upload", files={"file": ("notes.zip", b"not a zip", "application/zip")})
    assert bad.status_code == 422
    assert len((await admin.get(B)).json()["items"]) == 2


async def test_backup_names_cannot_escape_the_directory(admin) -> None:  # type: ignore[no-untyped-def]
    assert (await admin.get(f"{B}/..%2F..%2Fpyproject.toml/download")).status_code == 404
    assert (await admin.delete(f"{B}/erp-backup-20260101T000000Z-manual.zip")).status_code == 404


async def test_delete_removes_the_file(admin) -> None:  # type: ignore[no-untyped-def]
    name = await make_backup(admin)
    assert (await admin.delete(f"{B}/{name}")).status_code == 204
    assert (await admin.get(B)).json()["items"] == []
