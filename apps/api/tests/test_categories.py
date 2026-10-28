import io

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailed
from app.modules.categories import api as categories
from app.modules.categories.groups import GROUPS
from tests.conftest import ClientFactory

BASE = "/api/v1/categories"


async def _by_key(c, group: str, key: str) -> dict:  # type: ignore[no-untyped-def]
    rows = (await c.get(BASE, params={"group": group})).json()
    return next(r for r in rows if r["system_key"] == key)


async def test_every_group_is_seeded_with_other(admin) -> None:  # type: ignore[no-untyped-def]
    groups = (await admin.get(f"{BASE}/groups")).json()
    assert {g["key"] for g in groups} == set(GROUPS)
    assert all(g["can_manage"] for g in groups)
    for group in GROUPS:
        rows = (await admin.get(BASE, params={"group": group})).json()
        assert any(r["is_other"] for r in rows), group


async def test_other_subcategory_for_reuse(admin) -> None:  # type: ignore[no-untyped-def]
    other = await _by_key(admin, "payment_method", "other")
    res = await admin.post(
        BASE,
        json={
            "group_key": "payment_method",
            "name": "Wise Transfer",
            "parent_id": other["id"],
            "description": "Wise multi-currency account",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["path"] == "Other › Wise Transfer"

    dup = await admin.post(
        BASE, json={"group_key": "payment_method", "name": "wise transfer", "parent_id": other["id"]}
    )
    assert dup.status_code == 422
    assert dup.json()["errors"][0]["code"] == "duplicate"

    # Same name at a different level is fine.
    assert (await admin.post(BASE, json={"group_key": "payment_method", "name": "Wise Transfer"})).status_code == 201


async def test_parent_must_be_same_group(admin) -> None:  # type: ignore[no-untyped-def]
    other_expense = await _by_key(admin, "expense_category", "other")
    res = await admin.post(BASE, json={"group_key": "payment_method", "name": "X", "parent_id": other_expense["id"]})
    assert res.status_code == 422


async def test_config_is_validated_per_group(admin) -> None:  # type: ignore[no-untyped-def]
    bad_key = await admin.post(BASE, json={"group_key": "payment_method", "name": "X", "config": {"color": "red"}})
    assert bad_key.status_code == 422
    bad_type = await admin.post(
        BASE, json={"group_key": "payment_method", "name": "X", "config": {"requires_reference_no": "yes"}}
    )
    assert bad_type.status_code == 422
    ok = await admin.post(
        BASE, json={"group_key": "payment_method", "name": "X", "config": {"requires_reference_no": True}}
    )
    assert ok.status_code == 201


async def test_system_values_can_be_renamed_but_protected_ones_not_deactivated(admin) -> None:  # type: ignore[no-untyped-def]
    cash = await _by_key(admin, "payment_method", "cash")
    renamed = await admin.patch(f"{BASE}/{cash['id']}", json={"version": cash["version"], "name": "Cash (USD)"})
    assert renamed.status_code == 200 and renamed.json()["system_key"] == "cash"
    assert (await admin.post(f"{BASE}/{cash['id']}/deactivate")).status_code == 200  # not protected

    other = await _by_key(admin, "payment_method", "other")
    assert (await admin.post(f"{BASE}/{other['id']}/deactivate")).status_code == 403
    salary = await _by_key(admin, "payment_purpose", "employee_salary")
    assert (await admin.post(f"{BASE}/{salary['id']}/deactivate")).status_code == 403
    assert (await admin.delete(f"{BASE}/{other['id']}")).status_code == 403


async def test_deactivated_categories_are_hidden_from_pickers(admin) -> None:  # type: ignore[no-untyped-def]
    created = (await admin.post(BASE, json={"group_key": "project_type", "name": "Blockchain"})).json()
    await admin.post(f"{BASE}/{created['id']}/deactivate")
    active = (await admin.get(BASE, params={"group": "project_type"})).json()
    assert created["id"] not in {r["id"] for r in active}
    everything = (await admin.get(BASE, params={"group": "project_type", "include_inactive": True})).json()
    assert created["id"] in {r["id"] for r in everything}
    assert (await admin.post(f"{BASE}/{created['id']}/activate")).json()["is_active"] is True


async def test_parent_with_active_children_cannot_be_deactivated(admin) -> None:  # type: ignore[no-untyped-def]
    parent = (await admin.post(BASE, json={"group_key": "expense_category", "name": "Travel"})).json()
    await admin.post(BASE, json={"group_key": "expense_category", "name": "Flights", "parent_id": parent["id"]})
    assert (await admin.post(f"{BASE}/{parent['id']}/deactivate")).status_code == 409


async def test_cannot_move_under_own_child(admin) -> None:  # type: ignore[no-untyped-def]
    a = (await admin.post(BASE, json={"group_key": "expense_category", "name": "A"})).json()
    b = (await admin.post(BASE, json={"group_key": "expense_category", "name": "B", "parent_id": a["id"]})).json()
    res = await admin.patch(f"{BASE}/{a['id']}", json={"version": a["version"], "parent_id": b["id"]})
    assert res.status_code == 422


async def test_merge_keeps_history_and_resolves_canonical(admin, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    other = await _by_key(admin, "expense_category", "other")
    travel = (
        await admin.post(
            BASE, json={"group_key": "expense_category", "name": "Business Travel", "parent_id": other["id"]}
        )
    ).json()
    dupe = (
        await admin.post(
            BASE, json={"group_key": "expense_category", "name": "Travel expenses", "parent_id": other["id"]}
        )
    ).json()

    merged = await admin.post(f"{BASE}/{dupe['id']}/merge", json={"target_id": travel["id"]})
    assert merged.status_code == 200
    assert merged.json()["merged_into_id"] == travel["id"] and merged.json()["is_active"] is False

    import uuid

    assert await categories.canonical_id(db, uuid.UUID(dupe["id"])) == uuid.UUID(travel["id"])
    # A merged category can't be edited, merged again, or deleted while it is referenced by the merge.
    assert (
        await admin.patch(f"{BASE}/{dupe['id']}", json={"version": merged.json()["version"], "name": "x"})
    ).status_code == 409
    assert (await admin.delete(f"{BASE}/{travel['id']}")).status_code == 409

    unmerged = await admin.post(f"{BASE}/{dupe['id']}/unmerge")
    assert unmerged.status_code == 200 and unmerged.json()["is_active"] is True

    logs = (await admin.get("/api/v1/audit-logs", params={"entity_id": dupe["id"]})).json()
    assert {e["action"] for e in logs["items"]} >= {"category.created", "category.merged", "category.unmerged"}


async def test_merge_rules(admin) -> None:  # type: ignore[no-untyped-def]
    cash = await _by_key(admin, "payment_method", "cash")
    wise = (await admin.post(BASE, json={"group_key": "payment_method", "name": "Wise"})).json()
    assert (await admin.post(f"{BASE}/{cash['id']}/merge", json={"target_id": wise["id"]})).status_code == 403
    assert (await admin.post(f"{BASE}/{wise['id']}/merge", json={"target_id": wise["id"]})).status_code == 422
    other_project = await _by_key(admin, "project_type", "other")
    res = await admin.post(f"{BASE}/{wise['id']}/merge", json={"target_id": other_project["id"]})
    assert res.status_code == 422


async def test_delete_only_unreferenced(admin) -> None:  # type: ignore[no-untyped-def]
    unused = (await admin.post(BASE, json={"group_key": "document_category", "name": "Scratch"})).json()
    assert (await admin.delete(f"{BASE}/{unused['id']}")).status_code == 204

    used = (await admin.post(BASE, json={"group_key": "document_category", "name": "Invoice copy"})).json()
    company = (await admin.get("/api/v1/settings/company")).json()
    upload = await admin.post(
        "/api/v1/attachments",
        data={
            "entity_type": "company_settings",
            "entity_id": company["id"],
            "category_id": used["id"],
        },
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    res = await admin.delete(f"{BASE}/{used['id']}")
    assert res.status_code == 409 and "Deactivate or merge" in res.json()["detail"]


async def test_permissions_follow_group_domain(client_as: ClientFactory) -> None:
    pm = await client_as("project_manager")
    assert (await pm.post(BASE, json={"group_key": "project_type", "name": "Blockchain"})).status_code == 201
    assert (await pm.post(BASE, json={"group_key": "payment_method", "name": "Wise"})).status_code == 403

    fm = await client_as("finance_manager")
    assert (await fm.post(BASE, json={"group_key": "expense_category", "name": "Travel"})).status_code == 201
    assert (await fm.post(BASE, json={"group_key": "task_category", "name": "QA"})).status_code == 403

    employee = await client_as("employee")
    assert (await employee.get(BASE, params={"group": "payment_method"})).status_code == 200
    assert (await employee.post(BASE, json={"group_key": "task_category", "name": "QA"})).status_code == 403
    groups = (await employee.get(f"{BASE}/groups")).json()
    assert not any(g["can_manage"] for g in groups)


async def test_idempotent_create(admin) -> None:  # type: ignore[no-untyped-def]
    body = {"group_key": "payment_method", "name": "PayPal"}
    first = await admin.post(BASE, json=body, headers={"Idempotency-Key": "k-1"})
    again = await admin.post(BASE, json=body, headers={"Idempotency-Key": "k-1"})
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert again.headers.get("idempotent-replayed") == "true"
    rows = (await admin.get(BASE, params={"group": "payment_method", "q": "PayPal"})).json()
    assert len(rows) == 1

    conflict = await admin.post(BASE, json={**body, "name": "Stripe"}, headers={"Idempotency-Key": "k-1"})
    assert conflict.status_code == 409


async def test_validate_choice_enforces_other_description(db: AsyncSession) -> None:
    other = await categories.by_system_key(db, "payment_method", "other")
    cash = await categories.by_system_key(db, "payment_method", "cash")
    with pytest.raises(ValidationFailed) as exc:
        await categories.validate_choice(
            db,
            group_key="payment_method",
            category_id=other.id,
            other_text=" ",
            field="method_category_id",
            other_field="method_other_text",
        )
    assert exc.value.errors[0]["field"] == "method_other_text"
    assert (
        await categories.validate_choice(db, group_key="payment_method", category_id=other.id, other_text="Wise")
    ).id == other.id
    assert (
        await categories.validate_choice(db, group_key="payment_method", category_id=cash.id, other_text=None)
    ).id == cash.id
    with pytest.raises(ValidationFailed):
        await categories.validate_choice(db, group_key="expense_category", category_id=cash.id, other_text=None)
    with pytest.raises(ValidationFailed):
        await categories.validate_choice(db, group_key="payment_method", category_id=None, other_text=None)
