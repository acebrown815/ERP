import io
from decimal import Decimal

from tests.conftest import ClientFactory, create_user, login, new_client
from tests.factories import category_id, customer, employee, project

D = Decimal


async def test_parties(admin) -> None:  # type: ignore[no-untyped-def]
    c = await admin.post(
        "/api/v1/parties",
        json={"kind": "customer", "name": "Acme Corp", "email": "ap@acme.com", "default_currency": "eur"},
    )
    assert c.status_code == 201, c.text
    assert c.json()["number"] == "CUS-00001" and c.json()["default_currency"] == "EUR"
    s = (await admin.post("/api/v1/parties", json={"kind": "supplier", "name": "AWS"})).json()
    assert s["number"] == "SUP-00001"

    other = await admin.post(
        "/api/v1/parties",
        json={
            "kind": "other",
            "name": "Referral Partner",
            "subtype_category_id": await category_id("party_subtype", "other"),
        },
    )
    assert other.status_code == 422  # "Other" subtype needs a description
    other = await admin.post(
        "/api/v1/parties",
        json={
            "kind": "other",
            "name": "Referral Partner",
            "subtype_category_id": await category_id("party_subtype", "other"),
            "subtype_other_text": "Reseller",
        },
    )
    assert other.status_code == 201

    org = (await admin.post("/api/v1/organizations", json={"legal_name": "Acme Holdings Ltd"})).json()
    upd = await admin.patch(
        f"/api/v1/parties/{c.json()['id']}", json={"version": c.json()["version"], "organization_id": org["id"]}
    )
    assert upd.json()["organization_id"] == org["id"]

    customers = (await admin.get("/api/v1/parties", params={"kind": "customer"})).json()
    assert [p["name"] for p in customers["items"]] == ["Acme Corp"]
    assert (await admin.get("/api/v1/parties", params={"q": "aws"})).json()["total"] == 1
    assert (await admin.post("/api/v1/parties", json={"kind": "employee", "name": "x"})).status_code == 422


async def test_employee_creates_party_and_syncs_name(admin) -> None:  # type: ignore[no-untyped-def]
    res = await admin.post(
        "/api/v1/employees",
        json={
            "full_name": "Alice Dev",
            "email": "alice@example.com",
            "start_date": "2026-01-05",
            "employment_type_category_id": await category_id("employment_type", "contractor"),
        },
    )
    assert res.status_code == 201, res.text
    e = res.json()
    assert e["number"].startswith("EMP-")
    # Employee parties are not listed with customers/suppliers.
    assert (await admin.get("/api/v1/parties", params={"q": "Alice"})).json()["total"] == 0
    renamed = await admin.patch(f"/api/v1/employees/{e['id']}", json={"version": e["version"], "full_name": "Alice D."})
    assert renamed.status_code == 200
    bad = await admin.patch(
        f"/api/v1/employees/{e['id']}", json={"version": renamed.json()["version"], "end_date": "2025-01-01"}
    )
    assert bad.status_code == 422

    dept = await admin.post("/api/v1/departments", json={"name": "Engineering"})
    assert dept.status_code == 201
    assert (await admin.post("/api/v1/departments", json={"name": "engineering"})).status_code == 409


async def test_employee_scope_own_and_link_to_user(admin, client_as: ClientFactory) -> None:  # type: ignore[no-untyped-def]
    user_id = await create_user("alice@example.com", "employee")
    alice = await employee("Alice", user_id=user_id)
    await employee("Bob")
    async with new_client() as c:
        await login(c, "alice@example.com")
        mine = (await c.get("/api/v1/employees")).json()
        assert [e["full_name"] for e in mine["items"]] == ["Alice"]
        assert (await c.get("/api/v1/employees/me")).json()["id"] == alice
        others = (await admin.get("/api/v1/employees")).json()["items"]
        bob = next(e for e in others if e["full_name"] == "Bob")
        assert (await c.get(f"/api/v1/employees/{bob['id']}")).status_code == 404

    dup = await admin.post(
        "/api/v1/employees",
        json={
            "full_name": "Alice 2",
            "start_date": "2026-01-01",
            "user_id": user_id,
            "employment_type_category_id": await category_id("employment_type", "full_time"),
        },
    )
    assert dup.status_code == 422  # a user links to at most one employee


async def test_project_members_and_manager_scope(admin) -> None:  # type: ignore[no-untyped-def]
    pm_user = await create_user("pm@example.com", "project_manager")
    pm = await employee("Peter PM", user_id=pm_user)
    a, b = await employee("A"), await employee("B")
    abc, xyz = await customer("ABC"), await customer("XYZ")
    mine = await project("ABC Portal", abc, [(a, D(60)), (b, D(40))], manager_id=pm)
    theirs = await project("XYZ App", xyz, [(b, None)])

    async with new_client() as c:
        await login(c, "pm@example.com")
        listed = (await c.get("/api/v1/projects")).json()
        assert [p["name"] for p in listed["items"]] == ["ABC Portal"]
        assert (await c.get(f"/api/v1/projects/{theirs}")).status_code == 404
        # Customers visible to a PM are those of their projects.
        parties = (await c.get("/api/v1/parties")).json()
        assert [p["name"] for p in parties["items"]] == ["ABC"]
        team = (await c.get("/api/v1/employees")).json()
        assert {e["full_name"] for e in team["items"]} == {"Peter PM", "A", "B"}

        p = (await c.get(f"/api/v1/projects/{mine}")).json()
        over = await c.put(
            f"/api/v1/projects/{mine}/members",
            json={
                "members": [
                    {"employee_id": a, "default_allocation_pct": "70"},
                    {"employee_id": b, "default_allocation_pct": "40"},
                ]
            },
        )
        assert over.status_code == 422
        ok = await c.patch(f"/api/v1/projects/{mine}", json={"version": p["version"], "status": "on_hold"})
        assert ok.status_code == 200
        other = (await admin.get(f"/api/v1/projects/{theirs}")).json()
        denied = await c.patch(f"/api/v1/projects/{theirs}", json={"version": other["version"], "name": "x"})
        assert denied.status_code == 403


async def test_import_dry_run_then_commit(admin) -> None:  # type: ignore[no-untyped-def]
    csv_text = "kind,name,email\ncustomer,Globex,ap@globex.com\nsupplier,Initech,\nvendor,Bad Kind,\n"
    files = {"file": ("parties.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    dry = (await admin.post("/api/v1/imports/parties", data={"dry_run": "true"}, files=files)).json()
    assert dry["total"] == 3 and dry["created"] == 2 and dry["committed"] is False
    assert dry["errors"] == [{"row": 4, "column": "kind", "message": "customer, supplier or other"}]
    assert (await admin.get("/api/v1/parties")).json()["total"] == 0  # dry run wrote nothing

    files = {"file": ("parties.csv", io.BytesIO(csv_text.encode()), "text/csv")}
    real = (await admin.post("/api/v1/imports/parties", data={"dry_run": "false"}, files=files)).json()
    assert real["committed"] is False  # all-or-nothing: one bad row blocks the import
    assert (await admin.get("/api/v1/parties")).json()["total"] == 0

    good = "kind,name,email\ncustomer,Globex,ap@globex.com\nsupplier,Initech,\n"
    files = {"file": ("parties.csv", io.BytesIO(good.encode()), "text/csv")}
    real = (await admin.post("/api/v1/imports/parties", data={"dry_run": "false"}, files=files)).json()
    assert real["committed"] is True and real["created"] == 2
    assert (await admin.get("/api/v1/parties")).json()["total"] == 2

    emp_csv = "full_name,email,employment_type,department,start_date\nCarol,carol@x.com,Contractor,Design,2026-02-01\n"
    files = {"file": ("e.csv", io.BytesIO(emp_csv.encode()), "text/csv")}
    res = (await admin.post("/api/v1/imports/employees", data={"dry_run": "false"}, files=files)).json()
    assert res["committed"] is True, res
    proj_csv = (
        "name,customer,manager_email,project_type,contract_value,status\n"
        "Globex CRM,Globex,carol@x.com,Consulting,25000,active\n"
    )
    files = {"file": ("p.csv", io.BytesIO(proj_csv.encode()), "text/csv")}
    res = (await admin.post("/api/v1/imports/projects", data={"dry_run": "false"}, files=files)).json()
    assert res["committed"] is True, res
    projects = (await admin.get("/api/v1/projects")).json()["items"]
    assert projects[0]["name"] == "Globex CRM" and projects[0]["contract_value"] == "25000.0000"

    bad_cols = {"file": ("x.csv", io.BytesIO(b"nom,kind\n"), "text/csv")}
    res = await admin.post("/api/v1/imports/parties", data={"dry_run": "true"}, files=bad_cols)
    assert res.status_code == 422
    template = await admin.get("/api/v1/imports/projects/template")
    assert template.text.startswith("name,customer,manager_email,project_type")


async def test_import_requires_permission(client_as: ClientFactory) -> None:
    fm = await client_as("finance_manager")
    files = {"file": ("p.csv", io.BytesIO(b"kind,name\ncustomer,X\n"), "text/csv")}
    assert (await fm.post("/api/v1/imports/parties", data={"dry_run": "true"}, files=files)).status_code == 403
