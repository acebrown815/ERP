import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ids
from app.core.db import SessionLocal
from app.core.money import allocate, quantize, to_decimal
from app.core.numbering import next_number
from app.core.outbox import OutboxEvent, emit, on_event, process_batch

D = Decimal


class TestAllocate:
    def test_percent_split_sums_exactly(self) -> None:
        assert allocate(D("100"), [D(1), D(1), D(1)]) == [D("33.34"), D("33.33"), D("33.33")]

    def test_scenario_split(self) -> None:
        assert allocate(D("10000"), [D(60), D(40)]) == [D("6000.00"), D("4000.00")]

    def test_negative_total(self) -> None:
        parts = allocate(D("-10.00"), [D(1), D(2)])
        assert sum(parts) == D("-10.00")

    @pytest.mark.parametrize("total", ["0.01", "1", "99.99", "1234567.89", "0.07"])
    @pytest.mark.parametrize("weights", [[1], [1, 1], [3, 7], [1, 1, 1, 1, 1, 1, 1], [0, 5, 0]])
    def test_always_sums_to_total(self, total: str, weights: list[int]) -> None:
        parts = allocate(D(total), [D(w) for w in weights])
        assert sum(parts) == quantize(D(total), 2)
        assert all(p >= 0 for p in parts)

    def test_crypto_precision(self) -> None:
        parts = allocate(D("1"), [D(1), D(2)], precision=8)
        assert sum(parts) == D("1.00000000")

    def test_rejects_bad_weights(self) -> None:
        with pytest.raises(ValueError):
            allocate(D(1), [])
        with pytest.raises(ValueError):
            allocate(D(1), [D(0)])
        with pytest.raises(ValueError):
            allocate(D(1), [D(-1), D(2)])


def test_float_money_rejected() -> None:
    with pytest.raises(TypeError):
        to_decimal(0.1)  # type: ignore[arg-type]
    assert to_decimal("0.1") + to_decimal("0.2") == D("0.3")


def test_uuid7_version_and_order() -> None:
    a, b = ids.new_id(), ids.new_id()
    assert a.version == 7 and b.version == 7
    fa, fb = ids._uuid7_fallback(), ids._uuid7_fallback()
    assert fa.version == 7 and fa.variant == uuid.RFC_4122
    assert fa.int >> 80 <= fb.int >> 80  # millisecond timestamp prefix is monotonic
    # Many ids inside one millisecond still sort in creation order (rows ordered by created_at, id).
    burst = [ids._uuid7_fallback() for _ in range(2000)]
    assert burst == sorted(burst) and len(set(burst)) == len(burst)
    assert all(u.version == 7 and u.variant == uuid.RFC_4122 for u in burst)


async def test_number_series(db: AsyncSession) -> None:
    assert await next_number(db, "PE", date(2026, 3, 1)) == "PE-2026-00001"
    assert await next_number(db, "PE", date(2026, 12, 31)) == "PE-2026-00002"
    assert await next_number(db, "PE", date(2027, 1, 1)) == "PE-2027-00001"
    assert await next_number(db, "JE", date(2026, 1, 1)) == "JE-2026-00001"


class TestOutbox:
    async def test_event_only_visible_after_commit_and_processed_once(self) -> None:
        seen: list[dict] = []

        @on_event("test.ping")
        async def handler(_: AsyncSession, payload: dict) -> None:
            seen.append(payload)

        async with SessionLocal() as s:
            emit(s, "test.ping", {"n": 1})
            await s.rollback()  # rolled back -> never delivered
        async with SessionLocal() as s:
            emit(s, "test.ping", {"n": 2})
            await s.commit()

        assert await process_batch(SessionLocal) == 1
        assert await process_batch(SessionLocal) == 0
        assert seen == [{"n": 2}]

    async def test_failing_handler_is_retried_later(self) -> None:
        @on_event("test.fail")
        async def handler(_: AsyncSession, __: dict) -> None:
            raise RuntimeError("boom")

        async with SessionLocal() as s:
            emit(s, "test.fail", {})
            await s.commit()
        await process_batch(SessionLocal)
        async with SessionLocal() as s:
            event = (await s.execute(OutboxEvent.__table__.select())).one()
            assert event.attempts == 1
            assert event.processed_at is None
            assert "boom" in event.last_error
            assert event.available_at > event.created_at
