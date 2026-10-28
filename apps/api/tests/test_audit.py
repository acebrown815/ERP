import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import SessionLocal
from tests.conftest import ClientFactory


async def test_actions_are_audited_and_chain_verifies(admin, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    await admin.post("/api/v1/categories", json={"group_key": "payment_method", "name": "Wise"})
    logs = (await admin.get("/api/v1/audit-logs", params={"action": "category."})).json()
    assert logs["total"] == 1
    entry = logs["items"][0]
    assert entry["action"] == "category.created"
    assert entry["actor_user_id"] == admin.user_id
    assert entry["after"]["name"] == "Wise"
    assert entry["request_id"]

    status = (await admin.get("/api/v1/audit-logs/verify")).json()
    assert status["ok"] is True and status["rows_checked"] >= 2  # login + create


async def test_audit_log_rows_cannot_be_changed_or_deleted(admin) -> None:  # type: ignore[no-untyped-def]
    async with SessionLocal() as s:
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(text("UPDATE audit_log SET action = 'x'"))
        await s.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(text("DELETE FROM audit_log"))


async def test_tampering_is_detected(admin) -> None:  # type: ignore[no-untyped-def]
    await admin.post("/api/v1/categories", json={"group_key": "payment_method", "name": "Wise"})
    async with SessionLocal() as s:
        # Simulate someone with owner rights bypassing the trigger.
        await s.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
        await s.execute(text("UPDATE audit_log SET after = '{\"name\": \"Evil\"}' WHERE action = 'category.created'"))
        await s.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
        await s.commit()
    status = (await admin.get("/api/v1/audit-logs/verify")).json()
    assert status["ok"] is False and status["first_broken_id"] is not None


async def test_employees_cannot_read_audit_log(client_as: ClientFactory) -> None:
    c = await client_as("employee")
    assert (await c.get("/api/v1/audit-logs")).status_code == 403
