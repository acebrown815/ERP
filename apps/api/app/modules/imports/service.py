"""CSV import for parties, employees and projects. Dry run first; a real run is all-or-nothing."""

import csv
import io
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ValidationFailed, field_error
from app.modules.audit import api as audit
from app.modules.categories import api as categories
from app.modules.employees import api as employees
from app.modules.parties import api as parties
from app.modules.projects import api as projects

MAX_ROWS = 5000

COLUMNS: dict[str, dict[str, bool]] = {  # column -> required
    "parties": {
        "kind": True,
        "name": True,
        "contact_name": False,
        "email": False,
        "phone": False,
        "website": False,
        "default_currency": False,
        "notes": False,
    },
    "employees": {
        "full_name": True,
        "email": False,
        "phone": False,
        "job_title": False,
        "employment_type": False,
        "department": False,
        "start_date": True,
        "notes": False,
    },
    "projects": {
        "name": True,
        "customer": False,
        "manager_email": False,
        "project_type": True,
        "start_date": False,
        "deadline": False,
        "contract_value": False,
        "currency": False,
        "status": False,
        "description": False,
    },
}


@dataclass
class ImportResult:
    entity: str
    dry_run: bool
    total: int = 0
    created: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    committed: bool = False


class RowError(Exception):
    def __init__(self, column: str, message: str) -> None:
        super().__init__(message)
        self.column, self.message = column, message


def _date(value: str, column: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise RowError(column, "Use YYYY-MM-DD") from None


def _decimal(value: str, column: str) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        raise RowError(column, "Not a number") from None


async def _category(session: AsyncSession, group: str, value: str, column: str, default: str | None = None) -> Any:
    found = await categories.find(session, group, value or (default or ""))
    if found is None:
        raise RowError(column, f"No {group.replace('_', ' ')} called {value!r}")
    return found


async def _party(session: AsyncSession, actor: uuid.UUID, row: dict[str, str]) -> None:
    kind = row["kind"].lower()
    if kind not in ("customer", "supplier", "other"):
        raise RowError("kind", "customer, supplier or other")
    if await parties.find_by_name(session, kind, row["name"]):
        raise RowError("name", f"A {kind} with this name already exists")
    data = {
        k: row.get(k) or None
        for k in ("name", "contact_name", "email", "phone", "website", "default_currency", "notes")
    }
    await parties.create(session, actor_id=actor, kind=kind, data=data)


async def _employee(session: AsyncSession, actor: uuid.UUID, row: dict[str, str]) -> None:
    if row.get("email") and await employees.find_by_email(session, row["email"]):
        raise RowError("email", "An employee with this email already exists")
    etype = await _category(session, "employment_type", row.get("employment_type", ""), "employment_type", "full_time")
    dept_id = None
    if row.get("department"):
        dept = await employees.department_by_name(session, row["department"])
        dept = dept or await employees.create_department(session, actor_id=actor, name=row["department"])
        dept_id = dept.id
    await employees.create(
        session,
        actor_id=actor,
        data={
            "full_name": row["full_name"],
            "email": row.get("email") or None,
            "phone": row.get("phone") or None,
            "job_title": row.get("job_title") or None,
            "employment_type_category_id": etype.id,
            "department_id": dept_id,
            "start_date": _date(row["start_date"], "start_date"),
            "status": "active",
            "notes": row.get("notes") or None,
        },
    )


async def _project(session: AsyncSession, actor: uuid.UUID, row: dict[str, str]) -> None:
    ptype = await _category(session, "project_type", row["project_type"], "project_type")
    customer_id = None
    if row.get("customer"):
        customer = await parties.find_by_number(session, row["customer"]) or await parties.find_by_name(
            session, "customer", row["customer"]
        )
        if customer is None:
            raise RowError("customer", f"No customer {row['customer']!r} (use the name or CUS- number)")
        customer_id = customer.id
    manager_id = None
    if row.get("manager_email"):
        manager = await employees.find_by_email(session, row["manager_email"])
        if manager is None:
            raise RowError("manager_email", "No employee with this email")
        manager_id = manager.id
    status = (row.get("status") or "active").lower()
    if status not in ("planned", "active", "on_hold", "completed", "cancelled"):
        raise RowError("status", "planned, active, on_hold, completed or cancelled")
    await projects.create(
        session,
        actor_id=actor,
        data={
            "name": row["name"],
            "customer_party_id": customer_id,
            "manager_employee_id": manager_id,
            "project_type_category_id": ptype.id,
            "start_date": _date(row.get("start_date", ""), "start_date"),
            "deadline": _date(row.get("deadline", ""), "deadline"),
            "contract_value": _decimal(row.get("contract_value", ""), "contract_value"),
            "currency": row.get("currency") or None,
            "status": status,
            "description": row.get("description") or None,
        },
    )


HANDLERS: dict[str, Callable[[AsyncSession, uuid.UUID, dict[str, str]], Awaitable[None]]] = {
    "parties": _party,
    "employees": _employee,
    "projects": _project,
}


async def run(
    session: AsyncSession, *, actor_id: uuid.UUID, entity: str, content: bytes, dry_run: bool
) -> ImportResult:
    result = ImportResult(entity=entity, dry_run=dry_run)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationFailed(
            "File must be UTF-8 CSV", errors=[field_error("file", "Save the file as CSV UTF-8")]
        ) from None
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    columns = COLUMNS[entity]
    missing = [c for c, req in columns.items() if req and c not in headers]
    unknown = [h for h in headers if h not in columns]
    if missing or unknown:
        errors = [field_error("file", f"Missing column: {c}", "missing_column") for c in missing]
        errors += [field_error("file", f"Unknown column: {c}", "unknown_column") for c in unknown]
        raise ValidationFailed("The CSV columns don't match the template", errors=errors)

    for line_no, raw in enumerate(reader, start=2):
        if result.total >= MAX_ROWS:
            raise ValidationFailed(f"At most {MAX_ROWS} rows per import", errors=[field_error("file", "Too many rows")])
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        result.total += 1
        try:
            for column, required in columns.items():
                if required and not row.get(column):
                    raise RowError(column, "Required")
            async with session.begin_nested():
                await HANDLERS[entity](session, actor_id, row)
            result.created += 1
        except RowError as exc:
            result.errors.append({"row": line_no, "column": exc.column, "message": exc.message})
        except AppError as exc:
            for e in exc.errors or [{"field": "", "message": exc.detail}]:
                result.errors.append({"row": line_no, "column": e.get("field", ""), "message": e["message"]})

    if dry_run or result.errors:
        await session.rollback()
        return result
    await audit.record(
        session,
        actor_id=actor_id,
        action="import.completed",
        entity_type="import",
        entity_id=entity,
        after={"rows": result.created},
    )
    await session.commit()
    result.committed = True
    return result


def template(entity: str) -> str:
    return ",".join(COLUMNS[entity]) + "\n"
