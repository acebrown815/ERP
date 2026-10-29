"""Operations endpoints: consistency checks for administrators."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import checks
from app.core.db import get_session
from app.modules.auth.api import CurrentUser, require

router = APIRouter(tags=["system"])


class CheckOut(BaseModel):
    key: str
    label: str
    ok: bool
    detail: str


class ChecksOut(BaseModel):
    ok: bool
    ran_at: datetime
    checks: list[CheckOut]


@router.get("/system/checks", response_model=ChecksOut)
async def run_checks(
    _: CurrentUser = Depends(require("audit.read")), session: AsyncSession = Depends(get_session)
) -> ChecksOut:
    """Ledger ties, balance sheet balances, splits and salary records match payments, audit chain intact,
    worker keeping up. Also run nightly by the worker, which notifies administrators of failures."""
    results = await checks.run_all(session)
    return ChecksOut(
        ok=all(r.ok for r in results),
        ran_at=datetime.now().astimezone(),
        checks=[CheckOut(**vars(r)) for r in results],
    )
