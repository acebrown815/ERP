from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app import worker
from app.core import checks
from app.core.db import SessionLocal
from app.modules.backups import service as backups
from app.modules.calendar.models import Notification
from tests.conftest import create_user

SEOUL = ZoneInfo("Asia/Seoul")


def test_nightly_is_due_after_two_in_the_company_time_zone() -> None:
    assert not worker.nightly_due(datetime(2026, 11, 5, 1, 59, tzinfo=SEOUL), None)
    assert worker.nightly_due(datetime(2026, 11, 5, 2, 0, tzinfo=SEOUL), None)
    assert worker.nightly_due(datetime(2026, 11, 5, 2, 0, tzinfo=SEOUL), date(2026, 11, 4))
    assert not worker.nightly_due(datetime(2026, 11, 5, 23, 0, tzinfo=SEOUL), date(2026, 11, 5))


def test_a_restart_remembers_tonights_backup_in_the_company_time_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    # 18:00 UTC on the 4th is already 03:00 on the 5th in Seoul.
    monkeypatch.setattr(worker.backups, "last_automatic", lambda: datetime(2026, 11, 4, 18, 0, tzinfo=UTC))

    assert worker.last_nightly_run(SEOUL) == date(2026, 11, 5)
    assert worker.last_nightly_run(ZoneInfo("UTC")) == date(2026, 11, 4)


def test_a_first_run_has_no_last_nightly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker.backups, "last_automatic", lambda: None)
    assert worker.last_nightly_run(SEOUL) is None


async def notifications() -> list[Notification]:
    async with SessionLocal() as s:
        return list((await s.execute(select(Notification))).scalars())


async def test_a_failed_backup_notifies_administrators_once_a_day(monkeypatch: pytest.MonkeyPatch) -> None:
    await create_user("admin@example.com", "admin")
    await create_user("staff@example.com", "employee")

    async def broken() -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(worker.backups, "nightly", broken)
    await worker.nightly_backup_job()
    await worker.nightly_backup_job()

    sent = await notifications()
    assert len(sent) == 1
    assert sent[0].kind == "backup_failed" and "No space left" in (sent[0].body or "")


async def test_a_failed_check_notifies_administrators(monkeypatch: pytest.MonkeyPatch) -> None:
    await create_user("admin@example.com", "admin")

    async def bad(_: object) -> tuple[bool, str]:
        return False, "Off by 1.00"

    monkeypatch.setattr(checks, "_checks", [("broken", "Broken check", bad)])
    assert await worker.nightly_checks_job() is False

    sent = await notifications()
    assert [n.kind for n in sent] == ["system_check_failed"]
    assert "Off by 1.00" in (sent[0].body or "")


def _fake_backup(monkeypatch: pytest.MonkeyPatch, *, kind: str, age_hours: int) -> None:
    info = backups.BackupInfo(
        name=f"erp-backup-x-{kind}.zip",
        kind=kind,
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
        size=1,
        schema_version="x",
        rows=1,
        files=0,
    )
    monkeypatch.setattr(backups, "list_backups", lambda: [info])


def test_recent_backup_check(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_backup(monkeypatch, kind="auto", age_hours=20)
    assert backups.recent_backup(production=True)[0] is True

    _fake_backup(monkeypatch, kind="auto", age_hours=40)
    assert backups.recent_backup(production=True)[0] is False

    # Uploaded from elsewhere: it isn't evidence that this server is backing itself up.
    _fake_backup(monkeypatch, kind="upload", age_hours=1)
    assert backups.recent_backup(production=True)[0] is False
    assert backups.recent_backup(production=False)[0] is True
